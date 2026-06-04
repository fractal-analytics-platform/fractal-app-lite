<script>
	import DatasetTable from '$lib/components/DatasetTable.svelte';
	import {
		addDatasetStore,
		removeDatasetStore,
		loadDatasetCsv,
		saveDatasetCsv,
		clearDatasetImages
	} from '$lib/api.js';
	import { store, notify } from '$lib/stores.svelte.js';
	import { pickOpenDirectory, pickOpenFile, pickSaveFile } from '$lib/filepick.js';

	let busy = $state(false);

	async function addStore() {
		if (!store.project) {
			notify('Create or open a project first.', 'warning');
			return;
		}
		const path = await pickOpenDirectory('Select OME-Zarr store');
		if (!path) return;
		busy = true;
		try {
			const d = await addDatasetStore(path);
			store.dataset = d.dataset;
			notify(`Added ${path}`, 'positive');
		} catch (e) {
			notify(String(e.message ?? e), 'negative');
		} finally {
			busy = false;
		}
	}

	async function removeStore(url) {
		busy = true;
		try {
			const d = await removeDatasetStore(url);
			store.dataset = d.dataset;
			notify(`Removed ${url}`, 'positive');
		} catch (e) {
			notify(String(e.message ?? e), 'negative');
		} finally {
			busy = false;
		}
	}

	async function clearImages() {
		if (!store.project) {
			notify('Create or open a project first.', 'warning');
			return;
		}
		busy = true;
		try {
			const d = await clearDatasetImages();
			store.dataset = d.dataset;
			notify('Cleared all images', 'positive');
		} catch (e) {
			notify(String(e.message ?? e), 'negative');
		} finally {
			busy = false;
		}
	}

	async function loadCsv() {
		if (!store.project) {
			notify('Create or open a project first.', 'warning');
			return;
		}
		const path = await pickOpenFile('Open dataset CSV', ['CSV files (*.csv)', 'All files (*.*)']);
		if (!path) return;
		busy = true;
		try {
			const d = await loadDatasetCsv(path);
			store.dataset = d.dataset;
			notify(`Loaded ${d.dataset.name}`, 'positive');
		} catch (e) {
			notify(String(e.message ?? e), 'negative');
		} finally {
			busy = false;
		}
	}

	async function saveCsv() {
		if (!store.project) {
			notify('Create or open a project first.', 'warning');
			return;
		}
		const path = await pickSaveFile('Save dataset CSV', `${store.dataset?.name ?? 'dataset'}.csv`, [
			'CSV files (*.csv)',
			'All files (*.*)'
		]);
		if (!path) return;
		busy = true;
		try {
			await saveDatasetCsv(path);
			notify(`Saved to ${path}`, 'positive');
		} catch (e) {
			notify(String(e.message ?? e), 'negative');
		} finally {
			busy = false;
		}
	}
</script>

{#if !store.project}
	<div class="alert alert-info">
		No project open. Use <strong>New project</strong> or <strong>Open project</strong> in the top bar
		to get started.
	</div>
{/if}

<div class="card mb-3">
	<div class="card-header d-flex align-items-center justify-content-between">
		<span>Images</span>
		<div class="btn-group btn-group-sm">
			<button class="btn btn-outline-secondary" onclick={addStore} disabled={busy}>
				<i class="bi bi-plus-lg"></i> Add
			</button>
			<button class="btn btn-outline-secondary" onclick={loadCsv} disabled={busy}>
				<i class="bi bi-upload"></i> Load CSV
			</button>
			<button class="btn btn-outline-secondary" onclick={saveCsv} disabled={busy}>
				<i class="bi bi-download"></i> Save CSV
			</button>
			<button class="btn btn-outline-secondary" onclick={clearImages} disabled={busy}>
				<i class="bi bi-trash"></i> Clear
			</button>
		</div>
	</div>
	<div class="card-body">
		<DatasetTable dataset={store.dataset} onRemove={removeStore} />
	</div>
</div>
