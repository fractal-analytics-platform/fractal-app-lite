// Adds "Browse" buttons to path-like string inputs inside the schema-driven JSchema
// forms, without modifying the vendored components library. Used as a Svelte action on a
// wrapper around <JSchema>: it scans the rendered inputs, and for fields whose label
// looks like a filesystem path it injects a folder picker and a file picker that fill the
// input and notify Svelte's two-way binding. A MutationObserver re-applies the buttons
// when the form re-renders (task switch, array item added, etc.).

import { pickOpenFile, pickOpenDirectory } from '$lib/filepick.js';

// Heuristic: a field is path-like when its (case-insensitive) label mentions a
// path/dir/file/folder. Pydantic titles like "Zarr Dir" or "Input Path" match.
const PATH_FIELD_RE = /(^|[\s_])(path|dir|directory|folder|file)s?([\s_]|$)/;

/**
 * @param {string} text
 * @returns {boolean}
 */
export function isPathLikeField(text) {
	if (typeof text !== 'string') return false;
	const lower = text.toLowerCase();
	if (PATH_FIELD_RE.test(lower)) return true;
	return (
		lower.includes('path') ||
		lower.includes('dir') ||
		lower.includes('folder') ||
		lower.includes('file')
	);
}

/**
 * @param {string} icon Bootstrap icon class (e.g. "bi-folder2-open")
 * @param {string} label accessible label / tooltip
 * @returns {HTMLButtonElement}
 */
function makeButton(icon, label) {
	const btn = document.createElement('button');
	btn.type = 'button';
	btn.className = 'btn btn-outline-secondary';
	btn.title = label;
	btn.setAttribute('aria-label', label);
	const i = document.createElement('i');
	i.className = `bi ${icon}`;
	btn.appendChild(i);
	return btn;
}

/**
 * @param {HTMLInputElement} input
 * @param {string} title dialog title
 * @param {'file'|'directory'} kind
 */
async function browse(input, title, kind) {
	const picked =
		kind === 'directory' ? await pickOpenDirectory(title) : await pickOpenFile(title);
	if (picked) {
		input.value = picked;
		// Let Svelte's bind:value (and the form's validation) observe the change.
		input.dispatchEvent(new Event('input', { bubbles: true }));
	}
}

/**
 * @param {HTMLInputElement} input
 * @param {string} title
 */
function enhanceInput(input, title) {
	input.dataset.pathPicker = 'true';
	const container = /** @type {HTMLElement} */ (input.parentElement); // .property-input
	container.classList.add('input-group');
	const feedback = container.querySelector('.invalid-feedback');
	const dirBtn = makeButton('bi-folder2-open', 'Browse for a folder');
	const fileBtn = makeButton('bi-file-earmark', 'Browse for a file');
	dirBtn.addEventListener('click', () => browse(input, title, 'directory'));
	fileBtn.addEventListener('click', () => browse(input, title, 'file'));
	// Keep buttons before the validation feedback so Bootstrap's has-validation works.
	container.insertBefore(dirBtn, feedback);
	container.insertBefore(fileBtn, feedback);
}

/**
 * @param {HTMLElement} root
 */
function scan(root) {
	const inputs = root.querySelectorAll(
		'input.form-control[type="text"][id^="property-"]:not([data-path-picker])'
	);
	for (const el of inputs) {
		const input = /** @type {HTMLInputElement} */ (el);
		if (input.disabled) continue;
		const metadata = input.closest('.property-input')?.previousElementSibling;
		const title = (metadata?.textContent || '').trim();
		if (!isPathLikeField(title)) continue;
		enhanceInput(input, title);
	}
}

/**
 * Svelte action. Place on a wrapper element around <JSchema>.
 * @param {HTMLElement} node
 */
export function enhancePathFields(node) {
	const run = () => scan(node);
	const observer = new MutationObserver(run);
	observer.observe(node, { childList: true, subtree: true });
	// Initial pass after the form has rendered its inputs.
	queueMicrotask(run);
	return {
		destroy() {
			observer.disconnect();
		}
	};
}
