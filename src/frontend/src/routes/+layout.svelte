<script>
	// Bundle Bootstrap 5 + icons locally (offline-safe for a desktop app). The
	// fractal-components renderers rely on Bootstrap classes globally, and the
	// Bootstrap JS bundle drives the collapsible/accordion + tooltips they use.
	import 'bootstrap/dist/css/bootstrap.min.css';
	import 'bootstrap-icons/font/bootstrap-icons.css';
	import { onMount } from 'svelte';
	import Toasts from '$lib/components/Toasts.svelte';
	import PathModal from '$lib/components/PathModal.svelte';
	import NewProjectModal from '$lib/components/NewProjectModal.svelte';
	import { listTasks, openProject, saveProject } from '$lib/api.js';
	import { store, notify, refreshDataset, refreshProject } from '$lib/stores.svelte.js';
	import { pickOpenDirectory } from '$lib/filepick.js';

	let { children } = $props();

	let showNewProject = $state(false);

	onMount(async () => {
		await import('bootstrap/dist/js/bootstrap.bundle.min.js');
		// Pick up a project that was opened at startup (e.g. `--open <dir>`).
		await refreshTabs();
	});

	function toggleDark() {
		store.dark = !store.dark;
		document.documentElement.setAttribute('data-bs-theme', store.dark ? 'dark' : 'light');
	}

	// Re-read everything a new/opened project replaces: project info, registry, dataset.
	async function refreshTabs() {
		await refreshProject();
		store.tasks = await listTasks();
		await refreshDataset();
	}

	async function onProjectCreated() {
		await refreshTabs();
	}

	async function doOpenProject() {
		const dir = await pickOpenDirectory('Open project');
		if (!dir) return;
		try {
			await openProject(dir);
			await refreshTabs();
			notify(`Opened project from ${dir}`, 'positive');
		} catch (e) {
			notify(`Failed to open project: ${e.message ?? e}`, 'negative');
		}
	}

	async function doSaveProject() {
		if (!store.project) {
			notify('No project open to save.', 'warning');
			return;
		}
		try {
			await saveProject();
			notify(`Saved project to ${store.project.project_dir}`, 'positive');
		} catch (e) {
			notify(`Failed to save project: ${e.message ?? e}`, 'negative');
		}
	}
</script>

<nav class="navbar bg-body-tertiary border-bottom px-3">
	<div class="navbar-brand d-flex align-items-center gap-2 mb-0">
		<img src="/fractal_logo.png" alt="Fractal" width="28" height="28" style="object-fit: contain;" />
		<span class="h5 mb-0">Fractal Lite</span>
		{#if store.project}
			<span class="badge text-bg-secondary fw-normal" title={store.project.project_dir}>
				{store.project.name}
			</span>
		{/if}
	</div>
	<div class="d-flex align-items-center gap-2">
		<button class="btn btn-sm btn-outline-secondary" onclick={() => (showNewProject = true)}>
			<i class="bi bi-plus-square"></i> New project
		</button>
		<button class="btn btn-sm btn-outline-secondary" onclick={doOpenProject}>
			<i class="bi bi-folder2-open"></i> Open project
		</button>
		<button
			class="btn btn-sm btn-outline-secondary"
			onclick={doSaveProject}
			disabled={!store.project}
		>
			<i class="bi bi-save"></i> Save project
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
<NewProjectModal bind:open={showNewProject} onCreated={onProjectCreated} />
