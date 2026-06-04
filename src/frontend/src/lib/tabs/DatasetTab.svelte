<script>
	import DatasetTable from '$lib/components/DatasetTable.svelte';
	import {
		createDataset,
		addDatasetStore,
		removeDatasetStore,
		loadDatasetCsv,
		saveDatasetCsv
	} from '$lib/api.js';
	import { store, notify } from '$lib/stores.svelte.js';
	import { pickOpenDirectory, pickOpenFile, pickSaveFile } from '$lib/filepick.js';

	let dsName = $state('dataset');
	let dsZarrDir = $state('');
	let busy = $state(false);

	async function browseZarrDir() {
		const path = await pickOpenDirectory('Select zarr_dir');
		if (path) dsZarrDir = path;
	}

	async function create() {
		if (!dsZarrDir.trim()) {
			notify('Set a zarr_dir first.', 'warning');
			return;
		}
		busy = true;
		try {
			const d = await createDataset({ name: dsName || 'dataset', zarr_dir: dsZarrDir });
			store.dataset = d.dataset;
			notify(`Created empty dataset (zarr_dir: ${dsZarrDir})`, 'positive');
		} catch (e) {
			notify(String(e.message ?? e), 'negative');
		} finally {
			busy = false;
		}
	}

	async function addStore() {
		if (!store.dataset) {
			notify('Create a dataset first.', 'warning');
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

	async function loadCsv() {
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
		if (!store.dataset) {
			notify('No dataset to save.', 'warning');
			return;
		}
		const path = await pickSaveFile('Save dataset CSV', `${store.dataset.name}.csv`, [
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

<div class="card mb-3">
	<div class="card-header">New dataset</div>
	<div class="card-body">
		<div class="row g-2 align-items-end">
			<div class="col-sm-3">
				<label class="form-label" for="ds-name">Name</label>
				<input id="ds-name" class="form-control" bind:value={dsName} />
			</div>
			<div class="col-sm-6">
				<label class="form-label" for="ds-dir">zarr_dir</label>
				<div class="input-group">
					<input
						id="ds-dir"
						class="form-control"
						bind:value={dsZarrDir}
						placeholder="/abs/path/to/output_zarr"
					/>
					<button class="btn btn-outline-secondary" onclick={browseZarrDir} title="Browse…">
						<i class="bi bi-folder2-open"></i>
					</button>
				</div>
			</div>
			<div class="col-sm-3">
				<button class="btn btn-primary w-100" onclick={create} disabled={busy}>
					Create
				</button>
			</div>
		</div>
		<p class="form-text mb-0">The zarr_dir is created on disk so tasks have somewhere to write.</p>
	</div>
</div>

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
		</div>
	</div>
	<div class="card-body">
		<DatasetTable dataset={store.dataset} onRemove={removeStore} />
	</div>
</div>
