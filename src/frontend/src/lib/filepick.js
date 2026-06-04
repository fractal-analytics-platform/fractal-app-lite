// Unified path pickers. Each first asks the backend for a native OS dialog (available
// in the pywebview desktop window). If none is available (browser / `serve` mode), it
// falls back to a typed-path modal. All three resolve to an absolute path, or null if
// the user cancelled.

import { fsOpenFile, fsOpenDirectory, fsSaveFile } from '$lib/api.js';
import { promptForPath } from '$lib/stores.svelte.js';

export async function pickOpenFile(title, fileTypes = ['All files (*.*)']) {
	const res = await fsOpenFile(fileTypes);
	if (res.native) return res.path;
	return promptForPath(title);
}

export async function pickOpenDirectory(title) {
	const res = await fsOpenDirectory();
	if (res.native) return res.path;
	return promptForPath(title);
}

export async function pickSaveFile(title, defaultName = '', fileTypes = ['All files (*.*)']) {
	const res = await fsSaveFile(defaultName, fileTypes);
	if (res.native) return res.path;
	return promptForPath(title, defaultName);
}
