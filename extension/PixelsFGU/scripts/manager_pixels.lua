--
-- PixelsManager: feeds physical Pixels dice results into Fantasy Grounds.
--
-- The PixelsFGU bridge app writes connected dice and finished rolls to
-- <FG data folder>/PixelsFGU_inbox.json (see docs/protocol.md).
--
-- Flow:
--   * ActionsManager.roll is wrapped. If the roll contains at least one die type
--     the user has connected, it goes to CoreRPG's manual roll window instead of
--     the 3D dice. Otherwise it rolls normally.
--   * When a manual roll entry appears (ours, core's, or Requested Rolls'), slots
--     for dice the user does not own are filled digitally right away.
--   * The inbox is polled; each physical result goes into the first empty slot
--     of a matching type. When every slot is filled the roll is submitted, so
--     modifiers, advantage, targets, effects and damage resolve as usual.
--
-- FGU's Lua has no timer, per-frame event or file watcher (checked against the
-- FGU 5.1 engine), and a self-addressed OOB message is delivered synchronously
-- or not at all. So the bridge wakes us: after each roll it taps Shift while FGU
-- is the foreground window, and we poll on the global Input onShift event (also
-- onControl/onAlt). We also poll whenever a manual roll window opens.
--

local INBOX_FILE = "PixelsFGU_inbox.json";
local OUTBOX_FILE = "PixelsFGU_outbox.json";

local _sSession = nil;      -- bridge session id; changes when the bridge restarts
local _nLastSeq = 0;        -- highest roll seq handled in this session
local _tEntryOrder = {};    -- manual roll entry window -> arrival order
local _nEntryCounter = 0;
local _tPercentile = {};    -- d100 die window -> { tens = n, units = n }
local _tDigital = {};       -- die window -> true when we filled it digitally
local _tInventory = {};     -- FGU die type -> count of connected physical dice

local _nWakeups = 0;         -- input events that triggered a poll
local _nPollErrors = 0;
local _tProbeLog = {};

local fOriginalRoll = nil;
local fOriginalAddRoll = nil;

-------------------------------------------------------------------------------
-- Init
-------------------------------------------------------------------------------

function onInit()
	-- The extension can be enabled in any ruleset; stay inert where CoreRPG isn't underneath.
	if not (OptionsManager and OptionsManager.registerOptionData and Comm and Comm.registerSlashHandler) then
		Debug.console("[Pixels] This ruleset isn't based on CoreRPG; Pixels Dice is disabled.");
		return;
	end
	OptionsManager.registerOptionData({ sKey = "PIXELS_ENABLE", bLocal = true, sGroupRes = "option_header_pixels", sLabelRes = "option_label_PIXELS_ENABLE", tCustom = { default = "on" } });
	OptionsManager.registerOptionData({ sKey = "PIXELS_AUTOSUBMIT", bLocal = true, sGroupRes = "option_header_pixels", sLabelRes = "option_label_PIXELS_AUTOSUBMIT", tCustom = { default = "on" } });
	OptionsManager.registerOptionData({ sKey = "PIXELS_DIGITALFILL", bLocal = true, sGroupRes = "option_header_pixels", sLabelRes = "option_label_PIXELS_DIGITALFILL", tCustom = { default = "on" } });
	OptionsManager.registerOptionData({ sKey = "PIXELS_FREEROLL", bLocal = true, sGroupRes = "option_header_pixels", sLabelRes = "option_label_PIXELS_FREEROLL", tCustom = { default = "on" } });

	Comm.registerSlashHandler("pixels", PixelsManager.onSlashCommand, "[status|probe|reset]");

	Input.addEventHandler("onShift", PixelsManager.onWakeup);
	Input.addEventHandler("onControl", PixelsManager.onWakeup);
	Input.addEventHandler("onAlt", PixelsManager.onWakeup);
end

function onTabletopInit()
	-- Rulesets may replace ActionsManager.roll during their own init (2E does);
	-- by tabletop init it's final, so we wrap whatever is installed.
	if not (ActionsManager and ActionsManager.roll and ManualRollManager and ManualRollManager.addRoll) then
		Debug.console("[Pixels] This ruleset lacks CoreRPG's roll/manual-roll APIs; Pixels Dice is disabled.");
		return;
	end
	fOriginalRoll = ActionsManager.roll;
	ActionsManager.roll = PixelsManager.rollOverride;
	fOriginalAddRoll = ManualRollManager.addRoll;
	ManualRollManager.addRoll = PixelsManager.addRollOverride;

	-- Establish the baseline: rolls already in the inbox from before this
	-- session are skipped; everything after this is handled.
	PixelsManager.safePoll();
	PixelsManager.writeOutbox(); -- clear any stale "waiting" list
	PixelsManager.probe(false);
end

function isEnabled()
	return OptionsManager.isOption("PIXELS_ENABLE", "on");
end

local function log(s)
	Debug.console("[Pixels] " .. s);
end

function onWakeup()
	_nWakeups = _nWakeups + 1;
	PixelsManager.safePoll();
end

function safePoll()
	local bOK, vResult = pcall(PixelsManager.poll);
	if not bOK then
		_nPollErrors = _nPollErrors + 1;
		log("poll error: " .. tostring(vResult));
		return 0;
	end
	if vResult > 0 then
		log("handled " .. vResult .. " roll(s)");
	end
	return vResult;
end

-------------------------------------------------------------------------------
-- Inbox
-------------------------------------------------------------------------------

function getInboxPath()
	return File.getDataFolder() .. INBOX_FILE;
end

function readInbox()
	local bOK, sContents = pcall(File.openTextFile, PixelsManager.getInboxPath());
	if not bOK or type(sContents) ~= "string" or sContents == "" then
		return nil;
	end
	local tDoc = Utility.decodeJSON(sContents);
	if type(tDoc) ~= "table" then
		return nil;
	end
	return tDoc;
end

local BRIDGE_STALE_SECONDS = 60; -- bridge heartbeats every 15s

-- Is the bridge alive? It sets running=false on exit; the heartbeat age covers crashes.
function isBridgeRunning(tDoc)
	if not tDoc or tDoc.running == false then
		return false;
	end
	local bOK, nNow = pcall(function() return os.time(); end);
	local nUpdated = tonumber(tDoc.updated);
	if bOK and type(nNow) == "number" and nUpdated then
		return (nNow - nUpdated) < BRIDGE_STALE_SECONDS;
	end
	return true;
end

-- Dice the user owns: everything a running bridge knows about, including dice
-- that are asleep (Pixels drop the connection when left still and reconnect on
-- the next roll; the bridge reads that roll from the die's advertisement).
function updateInventory(tDoc)
	_tInventory = {};
	if not PixelsManager.isBridgeRunning(tDoc) then
		return;
	end
	for _, tDie in ipairs(tDoc.dice or {}) do
		local bOwned = tDie.connected or tDie.state == "asleep";
		if bOwned and type(tDie.die) == "string" then
			_tInventory[tDie.die] = (_tInventory[tDie.die] or 0) + 1;
		end
	end
end

function refreshInventory()
	PixelsManager.updateInventory(PixelsManager.readInbox());
end

function hasPhysical(sSlotDie)
	if sSlotDie == "d100" then
		return (_tInventory["d00"] or 0) > 0 and (_tInventory["d10"] or 0) > 0;
	end
	return (_tInventory[sSlotDie] or 0) > 0;
end

function poll()
	if not PixelsManager.isEnabled() then
		return 0;
	end
	local tDoc = PixelsManager.readInbox();
	if not tDoc then
		return 0;
	end
	PixelsManager.updateInventory(tDoc);

	if tDoc.session ~= _sSession then
		-- New bridge session. On the very first read, skip rolls already in the
		-- file so nothing from before FGU started is replayed.
		local bFirstRead = (_sSession == nil);
		_sSession = tDoc.session;
		_nLastSeq = bFirstRead and (tonumber(tDoc.lastseq) or 0) or 0;
		if bFirstRead then
			return 0;
		end
	end

	local nHandled = 0;
	for _, tRoll in ipairs(tDoc.rolls or {}) do
		local nSeq = tonumber(tRoll.seq) or 0;
		if nSeq > _nLastSeq then
			_nLastSeq = nSeq;
			PixelsManager.handleRoll(tRoll);
			nHandled = nHandled + 1;
		end
	end
	return nHandled;
end

-------------------------------------------------------------------------------
-- Routing rolls
-------------------------------------------------------------------------------

-- "d20", "-d6", "D20" -> "d20"
local function normalizeDieType(s)
	s = string.lower(s or "");
	return (s:gsub("^%-", ""));
end

local function dieTypeOf(vDie)
	if type(vDie) == "table" then
		return normalizeDieType(vDie.type);
	end
	return normalizeDieType(vDie);
end

function shouldUsePixels(rRoll)
	if not PixelsManager.isEnabled() or rRoll.bTower then
		return false;
	end
	if OptionsManager.isOption("MANUALROLL", "on") then
		return false; -- core already sends everything to the manual window
	end
	if not rRoll.aDice or rRoll.aDice.expr then
		return false;
	end
	PixelsManager.refreshInventory();
	for _, vDie in ipairs(rRoll.aDice) do
		if PixelsManager.hasPhysical(dieTypeOf(vDie)) then
			return true;
		end
	end
	return false;
end

function rollOverride(rSource, vTargets, rRoll, bMultiTarget)
	if ActionsManager.doesRollHaveDice(rRoll) and PixelsManager.shouldUsePixels(rRoll) then
		DiceManager.onPreEncodeRoll(rRoll);
		rRoll.sDesc = string.format("%s [%s]", rRoll.sDesc or "", Interface.getString("pixels_tag"));
		if bMultiTarget then
			ManualRollManager.addRoll(rRoll, rSource, vTargets);
		else
			ManualRollManager.addRoll(rRoll, rSource, { vTargets });
		end
		return;
	end
	return fOriginalRoll(rSource, vTargets, rRoll, bMultiTarget);
end

-- Every manual roll entry passes through here (core, ours, Requested Rolls).
function addRollOverride(rRoll, rSource, vTargets)
	fOriginalAddRoll(rRoll, rSource, vTargets);
	if not PixelsManager.isEnabled() then
		return;
	end
	PixelsManager.safePoll(); -- also refreshes inventory
	for _, wEntry in ipairs(PixelsManager.getPendingEntries()) do
		PixelsManager.lockEntry(wEntry);
		PixelsManager.fillDigital(wEntry);
	end
	PixelsManager.writeOutbox();
end

-- While Pixels handles a roll, values come only from physical dice or FGU's
-- own random numbers: the number fields are read-only and the OK / faux-roll
-- buttons are hidden. The "Roll" button stays: it rolls the whole thing with
-- FGU's 3D dice instead. Cancel stays too.
function lockEntry(wEntry)
	if next(_tInventory) == nil then
		return; -- no dice: leave normal manual entry alone
	end
	for _, wDie in ipairs(PixelsManager.getDieSlots(wEntry)) do
		wDie.value.setReadOnly(true);
	end
	if OptionsManager.isOption("PIXELS_AUTOSUBMIT", "on") then
		if wEntry.button_ok then wEntry.button_ok.setVisible(false); end
	end
	if wEntry.button_fauxroll then wEntry.button_fauxroll.setVisible(false); end
end

-------------------------------------------------------------------------------
-- Manual roll window helpers
-------------------------------------------------------------------------------

function getPendingEntries()
	local wMain = Interface.findWindow("manualrolls", "");
	if not wMain then
		return {};
	end

	local tEntries = {};
	for _, w in ipairs(wMain.list.getWindows()) do
		if not _tEntryOrder[w] then
			_nEntryCounter = _nEntryCounter + 1;
			_tEntryOrder[w] = _nEntryCounter;
		end
		-- Requested Rolls hides the dice list for complex expressions (e.g. 4d6d1); skip those.
		if w.list and w.list.isVisible() then
			table.insert(tEntries, w);
		end
	end
	table.sort(tEntries, function(a, b) return _tEntryOrder[a] < _tEntryOrder[b]; end);
	return tEntries;
end

function getDieSlots(wEntry)
	local tSlots = wEntry.list.getWindows();
	table.sort(tSlots, function(a, b) return a.sort.getValue() < b.sort.getValue(); end);
	return tSlots;
end

local function dieSides(sDie)
	return tonumber(sDie:match("^d(%d+)$"));
end

-- Fill slots for dice the user has no physical Pixel for.
function fillDigital(wEntry)
	if not OptionsManager.isOption("PIXELS_DIGITALFILL", "on") or next(_tInventory) == nil then
		return; -- no dice connected: leave the window for normal manual entry
	end
	local bAnyPhysical = false;
	for _, wDie in ipairs(PixelsManager.getDieSlots(wEntry)) do
		local sDie = normalizeDieType(wDie.label.getValue());
		if wDie.value.getValue() == 0 and not _tDigital[wDie] then
			if PixelsManager.hasPhysical(sDie) then
				bAnyPhysical = true;
			else
				local nSides = dieSides(sDie);
				if nSides and nSides > 0 then
					wDie.value.setValue(math.random(1, nSides));
					_tDigital[wDie] = true;
				end
			end
		end
	end
	-- Nothing left for physical dice (e.g. a Requested Roll for a die type we
	-- don't own): submit now so the player isn't left waiting.
	if not bAnyPhysical then
		PixelsManager.trySubmit(wEntry);
	end
end

-- First empty slot that accepts this die. Exact matches win over d100 slots,
-- which take a d00 (tens) and a d10 (units).
function findSlot(sDie)
	local tEntries = PixelsManager.getPendingEntries();
	local tPass = { "exact" };
	if sDie == "d10" or sDie == "d00" then
		table.insert(tPass, "percentile");
	end

	for _, sPass in ipairs(tPass) do
		for _, wEntry in ipairs(tEntries) do
			for _, wDie in ipairs(PixelsManager.getDieSlots(wEntry)) do
				if wDie.value.getValue() == 0 then
					local sSlotDie = normalizeDieType(wDie.label.getValue());
					if sPass == "exact" and sSlotDie == sDie then
						return wEntry, wDie, "exact";
					end
					if sPass == "percentile" and sSlotDie == "d100" then
						local tPart = _tPercentile[wDie] or {};
						if (sDie == "d00" and tPart.tens == nil) or (sDie == "d10" and tPart.units == nil) then
							return wEntry, wDie, "percentile";
						end
					end
				end
			end
		end
	end
	return nil;
end

function handleRoll(tRoll)
	local sDie = normalizeDieType(tRoll.die);
	local nValue = tonumber(tRoll.value) or 0;
	local nFace = tonumber(tRoll.face) or nValue;

	local wEntry, wDie, sMode = PixelsManager.findSlot(sDie);
	if wEntry then
		if sMode == "exact" then
			wDie.value.setValue(nValue);
		else
			local tPart = _tPercentile[wDie] or {};
			if sDie == "d00" then tPart.tens = nFace; else tPart.units = nFace; end
			_tPercentile[wDie] = tPart;
			if tPart.tens and tPart.units then
				local nTotal = tPart.tens + tPart.units;
				if nTotal == 0 then nTotal = 100; end
				_tPercentile[wDie] = nil;
				wDie.value.setValue(nTotal);
			end
		end
		PixelsManager.writeOutbox();
		PixelsManager.trySubmit(wEntry);
		return;
	end

	if sDie ~= "d00" and OptionsManager.isOption("PIXELS_FREEROLL", "on") then
		PixelsManager.postFreeRoll(sDie, nValue, tRoll.pixel or "Pixel");
	end
end

function trySubmit(wEntry)
	if not OptionsManager.isOption("PIXELS_AUTOSUBMIT", "on") then
		return;
	end
	for _, wDie in ipairs(PixelsManager.getDieSlots(wEntry)) do
		if wDie.value.getValue() == 0 then
			return;
		end
	end
	wEntry.processOK(); -- closes the entry; onEntryClosed handles the rest
end

-- Called from our manualroll_entry layer whenever an entry closes
-- (submitted, cancelled, or rolled with the 3D dice instead).
function onEntryClosed(wEntry)
	PixelsManager.writeOutbox(wEntry);
	_tEntryOrder[wEntry] = nil;
	for _, wDie in ipairs(wEntry.list.getWindows()) do
		_tDigital[wDie] = nil;
		_tPercentile[wDie] = nil;
	end

	-- CoreRPG leaves the empty "manualrolls" container open after its last
	-- entry closes. Requested Rolls closes it itself; otherwise we do.
	if not RR then
		local wList = wEntry.windowlist;
		if wList and wList.getWindowCount() <= 1 then
			wList.window.close();
		end
	end
end

-------------------------------------------------------------------------------
-- Outbox: tells the bridge which physical dice FGU is waiting on, so it can
-- blink them.
-------------------------------------------------------------------------------

local _sLastOutbox = nil;

function getWaitingDice(wSkipEntry)
	local tWaiting = {};
	for _, wEntry in ipairs(PixelsManager.getPendingEntries()) do
		if wEntry ~= wSkipEntry then
			for _, wDie in ipairs(PixelsManager.getDieSlots(wEntry)) do
				if wDie.value.getValue() == 0 then
					local sDie = normalizeDieType(wDie.label.getValue());
					if sDie == "d100" then
						local tPart = _tPercentile[wDie] or {};
						if PixelsManager.hasPhysical("d100") then
							if tPart.tens == nil then table.insert(tWaiting, "d00"); end
							if tPart.units == nil then table.insert(tWaiting, "d10"); end
						end
					elseif PixelsManager.hasPhysical(sDie) then
						table.insert(tWaiting, sDie);
					end
				end
			end
		end
	end
	return tWaiting;
end

function writeOutbox(wSkipEntry)
	local tWaiting = PixelsManager.isEnabled() and PixelsManager.getWaitingDice(wSkipEntry) or {};
	local sOut = "{\"version\":1,\"waiting\":[";
	for i, sDie in ipairs(tWaiting) do
		sOut = sOut .. (i > 1 and "," or "") .. "\"" .. sDie .. "\"";
	end
	sOut = sOut .. "]}";
	if sOut == _sLastOutbox then
		return;
	end
	_sLastOutbox = sOut;
	local bOK, sErr = pcall(File.saveTextFile, File.getDataFolder() .. OUTBOX_FILE, sOut);
	if not bOK then
		log("outbox write failed: " .. tostring(sErr));
	end
end

function postFreeRoll(sDie, nValue, sPixel)
	local rRoll = {
		sType = "dice",
		sDesc = string.format("[%s] %s", Interface.getString("pixels_tag"), sPixel),
		aDice = { { type = sDie, result = nValue, value = nValue } },
		nMod = 0,
	};
	ActionsManager.handleResolution(rRoll, nil, nil);
end

-------------------------------------------------------------------------------
-- Slash command and diagnostics (optional; nothing needs typing in play)
-------------------------------------------------------------------------------

function onSlashCommand(_, sParams)
	local sCmd = StringManager.trim(sParams or ""):lower();
	if sCmd == "probe" then
		PixelsManager.probe(true);
	elseif sCmd == "reset" then
		_sSession = nil;
		_nLastSeq = 0;
		_tPercentile = {};
		ChatManager.SystemMessage("[Pixels] Reset.");
	else
		PixelsManager.showStatus();
	end
end

function showStatus()
	local tDoc = PixelsManager.readInbox();
	PixelsManager.updateInventory(tDoc);
	local tLines = {
		"[Pixels] " .. (PixelsManager.isEnabled() and "Enabled" or "Disabled")
			.. ", wake-ups: " .. _nWakeups .. ", poll errors: " .. _nPollErrors,
	};
	if not tDoc then
		table.insert(tLines, "Bridge not detected (no " .. INBOX_FILE .. " in the data folder).");
	else
		table.insert(tLines, "Bridge " .. (PixelsManager.isBridgeRunning(tDoc) and "running" or "NOT running (normal dice in use)"));
		for _, tDie in ipairs(tDoc.dice or {}) do
			local sState = tDie.connected and "connected" or (tDie.state or "disconnected");
			table.insert(tLines, string.format("  %s: %s, %s, battery %s%%", tostring(tDie.name), tostring(tDie.die or tDie.pixels_type), sState, tostring(tDie.battery or "?")));
		end
		table.insert(tLines, "Last roll #" .. tostring(tDoc.lastseq or 0) .. ".");
	end
	ChatManager.SystemMessage(table.concat(tLines, "\n"));
end

function probeNote(s)
	table.insert(_tProbeLog, s);
	log("probe: " .. s);
end

function probe(bChat)
	PixelsManager.probeNote("host=" .. tostring(Session.IsHost) .. " user=" .. tostring(User.getUsername()));
	PixelsManager.probeNote("dataFolder=" .. tostring(File.getDataFolder()));
	local bRead, sRead = pcall(File.openTextFile, PixelsManager.getInboxPath());
	PixelsManager.probeNote("inbox read ok=" .. tostring(bRead) .. " bytes=" .. tostring(type(sRead) == "string" and #sRead or sRead));
	local bTime, nTime = pcall(function() return os.time(); end);
	local tDoc = PixelsManager.readInbox();
	PixelsManager.probeNote("os.time=" .. tostring(bTime and nTime) .. " inbox.updated=" .. tostring(tDoc and tDoc.updated) .. " bridgeRunning=" .. tostring(PixelsManager.isBridgeRunning(tDoc)));
	local tTypes = {};
	for k, n in pairs(_tInventory) do table.insert(tTypes, n .. "x" .. k); end
	PixelsManager.probeNote("inventory: " .. (#tTypes > 0 and table.concat(tTypes, ", ") or "none"));
	PixelsManager.probeNote("wakeups=" .. _nWakeups .. " lastSeq=" .. _nLastSeq .. " session=" .. tostring(_sSession));
	if bChat then
		ChatManager.SystemMessage("[Pixels probe]\n" .. table.concat(_tProbeLog, "\n"));
	end
end
