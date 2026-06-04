// Shared, app-wide reactive state (Svelte 5 runes in a `.svelte.js` module). A single
// process, single user: a couple of module-level `$state` objects are plenty, and they
// are mutated in place from any tab so cross-tab refresh is automatic.

import { getDataset, getProject } from '$lib/api.js';

// The open project (ProjectInfo dict, or null when none is open), the shared dataset
// (model_dump dict) and the registered tasks list.
export const store = $state({
	project: null,
	dataset: null,
	tasks: [],
	dark: false
});

// Transient toast notifications.
export const toasts = $state({ items: [] });

let _toastId = 0;

export function notify(message, type = 'info', timeout = 4000) {
	const id = ++_toastId;
	toasts.items.push({ id, message: String(message), type });
	if (timeout) {
		setTimeout(() => dismissToast(id), timeout);
	}
	return id;
}

export function dismissToast(id) {
	const i = toasts.items.findIndex((t) => t.id === id);
	if (i !== -1) toasts.items.splice(i, 1);
}

// Re-read the shared dataset from the backend into the store.
export async function refreshDataset() {
	const d = await getDataset();
	store.dataset = d.dataset;
	return store.dataset;
}

// Re-read the open project (ProjectInfo, or null) from the backend into the store.
export async function refreshProject() {
	store.project = await getProject();
	return store.project;
}

// --- Typed-path modal (fallback when no native OS dialog is available) ----- //

// Driven by `filepick.svelte.js`; the modal component in the layout renders this.
export const pathModal = $state({
	open: false,
	title: '',
	value: '',
	resolve: null
});

export function promptForPath(title, defaultValue = '') {
	return new Promise((resolve) => {
		pathModal.title = title;
		pathModal.value = defaultValue;
		pathModal.resolve = resolve;
		pathModal.open = true;
	});
}

export function resolvePathModal(value) {
	const resolve = pathModal.resolve;
	pathModal.open = false;
	pathModal.resolve = null;
	if (resolve) resolve(value || null);
}
