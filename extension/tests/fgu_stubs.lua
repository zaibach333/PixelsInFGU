--
-- Minimal stand-ins for the Fantasy Grounds APIs that manager_pixels.lua uses,
-- so its roll-routing logic can be tested outside FGU (see test_extension.py).
-- Returns a function that builds a fresh environment for each test.
--

return function(decodeJSON)
	local E = setmetatable({}, { __index = _G });
	E.PixelsManager = E; -- FGU exposes a global script's functions as PixelsManager.*

	E.T = {                 -- test-visible state
		options = {
			PIXELS_ENABLE = "on", PIXELS_AUTOSUBMIT = "on",
			PIXELS_DIGITALFILL = "on", PIXELS_FREEROLL = "on", MANUALROLL = "off",
		},
		inbox = nil,        -- JSON text returned by File.openTextFile for the inbox
		outbox = nil,       -- last JSON text written to the outbox
		submitted = {},     -- entries that were processOK'd, in order
		resolutions = {},   -- rolls passed to ActionsManager.handleResolution
		originalRolls = {}, -- rolls passed through to the original ActionsManager.roll
		console = {},
	};
	local T = E.T;

	E.Debug = { console = function(s) table.insert(T.console, s); end };
	E.OptionsManager = {
		registerOptionData = function() end,
		registerCallback = function() end,
		isOption = function(k, v) return T.options[k] == v; end,
		setOption = function(k, v) T.options[k] = v; end,
	};
	E.Comm = { registerSlashHandler = function() end };
	E.Input = { addEventHandler = function() end };
	E.Session = { IsHost = true };
	E.User = { getUsername = function() return "GM"; end };
	E.ChatManager = { SystemMessage = function() end };
	E.StringManager = { trim = function(s) return (s:gsub("^%s+", ""):gsub("%s+$", "")); end };
	E.Utility = { decodeJSON = decodeJSON };
	E.File = {
		getDataFolder = function() return "C:/FG/"; end,
		openTextFile = function(path)
			if path:find("PixelsFGU_inbox.json", 1, true) then return T.inbox; end
			return nil;
		end,
		saveTextFile = function(path, s) T.outbox = s; end,
	};
	E.Interface = {
		getString = function(k) return k == "pixels_tag" and "PIXELS" or k; end,
		findWindow = function(sClass)
			if sClass == "manualrolls" and T.main and not T.main.closed then return T.main; end
			return nil;
		end,
	};
	E.DiceManager = { onPreEncodeRoll = function() end };
	E.ActionsManager = {
		doesRollHaveDice = function(r) return r.aDice and #r.aDice > 0; end,
		handleResolution = function(r) table.insert(T.resolutions, r); end,
		roll = function(rSource, vTargets, rRoll) table.insert(T.originalRolls, rRoll); end,
	};

	-- Fake controls / windows -------------------------------------------------

	local function control(v)
		local c = { v = v, visible = true, readonly = false };
		function c.getValue() return c.v; end
		function c.setValue(x) c.v = x; end
		function c.isVisible() return c.visible; end
		function c.setVisible(b) c.visible = b; end
		function c.setReadOnly(b) c.readonly = b; end
		return c;
	end

	local function newMain()
		local main = { closed = false, entries = {} };
		main.list = {};
		function main.list.getWindows()
			local t = {};
			for _, w in ipairs(main.entries) do t[#t + 1] = w; end
			return t;
		end
		function main.list.getWindowCount() return #main.entries; end
		main.list.window = main;
		function main.close() main.closed = true; end
		return main;
	end

	-- Mirrors CoreRPG's manualroll_entry.setData: one slot per die in rRoll.aDice.
	local function newEntry(main, rRoll)
		local entry = { rRoll = rRoll, slots = {}, windowlist = main.list };
		for i, vDie in ipairs(rRoll.aDice) do
			local sType = type(vDie) == "table" and vDie.type or vDie;
			entry.slots[i] = { sort = control(i), label = control(sType), value = control(0) };
		end
		entry.button_ok = control(nil);
		entry.button_fauxroll = control(nil);
		entry.list = control(nil);
		function entry.list.getWindows()
			local t = {};
			for _, s in ipairs(entry.slots) do t[#t + 1] = s; end
			return t;
		end
		function entry.processOK()
			local tValues = {};
			for i, s in ipairs(entry.slots) do tValues[i] = s.value.getValue(); end
			table.insert(T.submitted, { entry = entry, values = tValues });
			E.PixelsManager.onEntryClosed(entry); -- our onClose layer
			for i, w in ipairs(main.entries) do
				if w == entry then table.remove(main.entries, i); break; end
			end
		end
		return entry;
	end

	E.ManualRollManager = {
		addRoll = function(rRoll)
			if not T.main or T.main.closed then T.main = newMain(); end
			table.insert(T.main.entries, newEntry(T.main, rRoll));
		end,
	};

	return E;
end
