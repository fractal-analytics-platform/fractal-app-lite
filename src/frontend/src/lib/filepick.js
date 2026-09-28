// Unified path pickers. Inside the Electron shell they use its native dialogs (exposed
// by the preload script as `window.fractalElectron`). Otherwise each asks the backend
// for a native OS dialog (available in the pywebview desktop window), and if none is
// available (browser / `serve` mode) falls back to a typed-path modal. All three
// resolve to an absolute path, or null if the user cancelled.

import { fsOpenFile, fsOpenDirectory, fsSaveFile } from '$lib/api.js';
import { promptForPath } from '$lib/stores.svelte.js';

const electron = typeof window !== 'undefined' ? window.fractalElectron : undefined;

export async function pickOpenFile(title, fileTypes = ['All files (*.*)']) {
	if (electron?.openFile) return electron.openFile(fileTypes);
	const res = await fsOpenFile(fileTypes);
	if (res.native) return res.path;
	return promptForPath(title);
}

export async function pickOpenDirectory(title) {
	if (electron?.openDirectory) return electron.openDirectory();
	const res = await fsOpenDirectory();
	if (res.native) return res.path;
	return promptForPath(title);
}

export async function pickSaveFile(title, defaultName = '', fileTypes = ['All files (*.*)']) {
	if (electron?.saveFile) return electron.saveFile(defaultName, fileTypes);
	const res = await fsSaveFile(defaultName, fileTypes);
	if (res.native) return res.path;
	return promptForPath(title, defaultName);
}
