<script>
	// Bundle Bootstrap 5 + icons locally (offline-safe for a desktop app). The
	// fractal-components renderers rely on Bootstrap classes globally, and the
	// Bootstrap JS bundle drives the collapsible/accordion + tooltips they use.
	import 'bootstrap/dist/css/bootstrap.min.css';
	import 'bootstrap-icons/font/bootstrap-icons.css';
	import { onMount } from 'svelte';
	import Toasts from '$lib/components/Toasts.svelte';
	import PathModal from '$lib/components/PathModal.svelte';
	import { listTasks, saveSession, loadSession } from '$lib/api.js';
	import { store, notify, refreshDataset } from '$lib/stores.svelte.js';
	import { pickOpenFile, pickSaveFile } from '$lib/filepick.js';

	let { children } = $props();

	onMount(async () => {
		await import('bootstrap/dist/js/bootstrap.bundle.min.js');
	});

	function toggleDark() {
		store.dark = !store.dark;
		document.documentElement.setAttribute('data-bs-theme', store.dark ? 'dark' : 'light');
	}

	async function doSaveSession() {
		const path = await pickSaveFile('Save session', 'state.json', [
			'JSON (*.json)',
			'All files (*.*)'
		]);
		if (!path) return;
		try {
			await saveSession(path);
			notify(`Saved session to ${path}`, 'positive');
		} catch (e) {
			notify(`Failed to save session: ${e.message ?? e}`, 'negative');
		}
	}

	async function doLoadSession() {
		const path = await pickOpenFile('Load session', ['JSON (*.json)', 'All files (*.*)']);
		if (!path) return;
		try {
			await loadSession(path);
			// A session restore replaces the dataset + registry; refresh every tab.
			store.tasks = await listTasks();
			await refreshDataset();
			notify(`Loaded session from ${path}`, 'positive');
		} catch (e) {
			notify(`Failed to load session: ${e.message ?? e}`, 'negative');
		}
	}
</script>

<nav class="navbar bg-body-tertiary border-bottom px-3">
	<div class="navbar-brand d-flex align-items-center gap-2 mb-0">
		<img src="/fractal_logo.png" alt="Fractal" width="28" height="28" style="object-fit: contain;" />
		<span class="h5 mb-0">Fractal Lite</span>
	</div>
	<div class="d-flex align-items-center gap-2">
		<button class="btn btn-sm btn-outline-secondary" onclick={doSaveSession}>
			<i class="bi bi-save"></i> Save session
		</button>
		<button class="btn btn-sm btn-outline-secondary" onclick={doLoadSession}>
			<i class="bi bi-folder2-open"></i> Load session
		</button>
		<button
			class="btn btn-sm btn-outline-secondary"
			onclick={toggleDark}
			title="Toggle dark mode"
			aria-label="Toggle dark mode"
		>
			<i class="bi {store.dark ? 'bi-sun' : 'bi-moon-stars'}"></i>
		</button>
	</div>
</nav>

<main class="container-fluid py-3">
	{@render children()}
</main>

<Toasts />
<PathModal />
