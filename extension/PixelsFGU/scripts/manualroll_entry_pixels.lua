--
-- Pixels layer on the manual roll entry window.
--

function onClose()
	if super and super.onClose then
		super.onClose();
	end
	PixelsManager.onEntryClosed(self);
end
