<script>
	import { tick } from 'svelte';
	import { JSchema, stripNullAndEmptyObjectsAndArrays } from 'fractal-components';
	import DatasetTable from '$lib/components/DatasetTable.svelte';
	import {
		getTaskSchema,
		runTask,
		cancelRun,
		listHistory,
		previewDataset,
		exportParams,
		importParams
	} from '$lib/api.js';
	import { connectRunSocket } from '$lib/ws.js';
	import { store, notify } from '$lib/stores.svelte.js';
	import { pickOpenFile, pickSaveFile } from '$lib/filepick.js';
	import { enhancePathFields } from '$lib/pathfield.js';
	import TaskFilters from '$lib/components/TaskFilters.svelte';

	// Args each task's run method injects itself, hidden from the forms (mirrors the
	// NiceGUI _INIT_HIDDEN / _PARALLEL_HIDDEN in sandbox_tab.py).
	const HIDDEN = {
		non_parallel: ['zarr_dir', 'zarr_urls'],
		parallel: ['zarr_url', 'init_args']
	};

	let selectedName = $state(''); // holds the selected task's unique_id
	let filteredTasks = $state([]); // task list narrowed by TaskFilters
	let phases = $state([]); // [{ phase, schema }]
	let formRefs = $state({}); // phase -> JSchema instance
	let formValid = $state({}); // phase -> boolean

	// Transient per-run filters: [{ attribute, value }].
	let filters = $state([]);
	// Transient per-run type filters: [{ key, value }] (value is a boolean).
	let typeFilters = $state([]);
	let filtersOpen = $state(false); // Filters card collapsed by default
	let preview = $state(null);

	let maxWorkers = $state(1);
	let running = $state(false);
	let jobId = $state(null);
	let socket = null;
	let logLines = $state([]);
	let summary = $state('');
	let metrics = $state(null); // { total_seconds, mean_item_seconds }
	let view = $state('log'); // 'log' | 'dataset'

	let history = $state([]);

	const selectedTask = $derived(store.tasks.find((t) => t.unique_id === selectedName) ?? null);
	const allValid = $derived(phases.every((p) => formValid[p.phase] !== false));
	const filterPairs = $derived(filters.map((f) => [f.attribute, f.value]));
	const typeFilterPairs = $derived(typeFilters.map((f) => [f.key, f.value]));

	// Live preview: refresh whenever the filters or the selected task change.
	const previewKey = $derived(
		JSON.stringify({ f: filterPairs, tf: typeFilterPairs, t: selectedName })
	);
	$effect(() => {
		previewKey; // track
		refreshPreview();
	});

	async function refreshPreview() {
		if (!store.dataset) {
			preview = null;
			return;
		}
		try {
			preview = await previewDataset(filterPairs, typeFilterPairs);
		} catch {
			preview = null;
		}
	}

	async function selectTask(name, seed) {
		phases = [];
		formRefs = {};
		formValid = {};
		const task = store.tasks.find((t) => t.unique_id === name);
		if (!task) return;
		const wanted = [];
		if (task.has_non_parallel) wanted.push('non_parallel');
		if (task.has_parallel) wanted.push('parallel');
		try {
			const loaded = [];
			for (const phase of wanted) {
				const res = await getTaskSchema(name, phase);
				loaded.push({ phase, schema: res.json_schema });
			}
			phases = loaded;
			await tick();
			for (const { phase, schema } of phases) {
				formRefs[phase]?.update(schema, seed?.[phase] ?? undefined);
			}
		} catch (e) {
			notify(String(e.message ?? e), 'negative');
		}
	}

	function onSelectTask() {
		summary = '';
		logLines = [];
		metrics = null;
		selectTask(selectedName);
	}

	// --- Filters ----------------------------------------------------------- //

	function addFilter() {
		filters.push({ attribute: '', value: '' });
	}
	function removeFilter(i) {
		filters.splice(i, 1);
	}
	function addTypeFilter() {
		typeFilters.push({ key: '', value: true });
	}
	function removeTypeFilter(i) {
		typeFilters.splice(i, 1);
	}

	// --- Run / cancel ------------------------------------------------------ //

	function readKwargs() {
		const out = { kwargs_non_parallel: null, kwargs_parallel: null };
		for (const { phase } of phases) {
			const ref = formRefs[phase];
			if (!ref) continue;
			const args = stripNullAndEmptyObjectsAndArrays(ref.getArguments());
			out[`kwargs_${phase}`] = Object.keys(args).length ? args : null;
		}
		return out;
	}

	async function run() {
		if (!store.dataset) {
			notify('Create or load a dataset first.', 'warning');
			return;
		}
		const kwargs = readKwargs();
		logLines = [];
		summary = '';
		metrics = null;
		view = 'log';
		running = true;
		try {
			const res = await runTask({
				task_name: selectedName,
				...kwargs,
				filters: filterPairs.filter(([a]) => a),
				type_filters: typeFilterPairs.filter(([k]) => k),
				max_workers: Number(maxWorkers) || 1
			});
			jobId = res.job_id;
			socket = connectRunSocket(jobId, {
				onLog: (line) => {
					logLines.push(line);
				},
				onDone: (msg) => {
					summary = `${msg.status}: ${msg.summary}`;
					metrics = {
						total_seconds: msg.total_seconds,
						mean_item_seconds: msg.mean_item_seconds
					};
					if (msg.dataset) store.dataset = msg.dataset;
					if (msg.status === 'completed') {
						view = 'dataset';
						notify('Run completed.', 'positive');
					} else {
						notify('Run cancelled.', 'warning');
					}
					finishRun();
				},
				onError: (msg) => {
					notify(msg.detail ?? 'Run failed.', 'negative');
					logLines.push(`ERROR: ${msg.detail ?? 'Run failed.'}`);
					finishRun();
				}
			});
			await refreshHistory();
		} catch (e) {
			notify(String(e.message ?? e), 'negative');
			finishRun();
		}
	}

	function finishRun() {
		running = false;
		jobId = null;
		if (socket) {
			socket.close();
			socket = null;
		}
		refreshHistory();
	}

	async function cancel() {
		if (!jobId) return;
		try {
			await cancelRun(jobId);
			notify('Cancelling…', 'warning');
		} catch (e) {
			notify(String(e.message ?? e), 'negative');
		}
	}

	// --- History / restore ------------------------------------------------- //

	function statusIcon(status) {
		if (status === 'cancelled') return 'bi-slash-circle-fill text-warning';
		if (status === 'failed') return 'bi-x-circle-fill text-danger';
		return 'bi-check-circle-fill text-success';
	}

	async function refreshHistory() {
		try {
			history = await listHistory();
		} catch {
			// non-fatal
		}
	}

	async function restore(rec) {
		selectedName = rec.task_name;
		filters = (rec.filters ?? []).map(([attribute, value]) => ({ attribute, value }));
		typeFilters = (rec.type_filters ?? []).map(([key, value]) => ({ key, value }));
		await selectTask(rec.task_name, {
			non_parallel: rec.kwargs_non_parallel ?? undefined,
			parallel: rec.kwargs_parallel ?? undefined
		});
		notify(`Restored run #${rec.index}`, 'positive');
	}

	// --- Export / import params ------------------------------------------- //

	async function doExport() {
		if (!selectedName) {
			notify('Select a task first.', 'warning');
			return;
		}
		const kwargs = readKwargs();
		const path = await pickSaveFile('Export parameters', `${selectedName}_params.json`, [
			'JSON (*.json)',
			'All files (*.*)'
		]);
		if (!path) return;
		try {
			await exportParams({ path, ...kwargs });
			notify(`Exported parameters to ${path}`, 'positive');
		} catch (e) {
			notify(String(e.message ?? e), 'negative');
		}
	}

	async function doImport() {
		if (!selectedName) {
			notify('Select a task first.', 'warning');
			return;
		}
		const path = await pickOpenFile('Import parameters', ['JSON (*.json)', 'All files (*.*)']);
		if (!path) return;
		try {
			const data = await importParams(path);
			await selectTask(selectedName, {
				non_parallel: data.kwargs_non_parallel ?? undefined,
				parallel: data.kwargs_parallel ?? undefined
			});
			notify('Imported parameters', 'positive');
		} catch (e) {
			notify(String(e.message ?? e), 'negative');
		}
	}

	$effect(() => {
		refreshHistory();
	});
</script>

<!-- Dataset banner -->
<div class="card mb-3">
	<div class="card-body py-2">
		{#if store.dataset}
			<span class="text-body-secondary small">
				Dataset: <strong>{store.dataset.name}</strong> —
				<code>{store.dataset.zarr_dir}</code> — {store.dataset.zarr_urls.length} image(s)
			</span>
		{:else}
			<span class="text-warning small">
				No dataset. Create or load one in the Dataset tab first.
			</span>
		{/if}
	</div>
</div>

<!-- How the sandbox treats the dataset -->
<div class="alert alert-warning d-flex py-2 mb-3" role="note">
	<i class="bi bi-exclamation-triangle me-2 mt-1"></i>
	<div class="small">
		<strong>Warning!</strong> The Sandbox page lets you run tasks independently of the workflow.
		Only the task's <strong>newly produced images</strong> are added back to the shared dataset —
		existing images' <code>active</code> state and types are never modified by a run. So running
		tasks one-by-one here is <strong>not</strong> the same as a chained workflow. Filters apply to
		a <em>fresh copy</em> of the dataset; use the filters below to choose which images each run
		processes.
	</div>
</div>

<!-- Filters + live preview -->
<div class="card mb-3">
	<div
		class="card-header d-flex align-items-center"
		role="button"
		tabindex="0"
		onclick={() => (filtersOpen = !filtersOpen)}
		onkeydown={(e) => {
			if (e.key === 'Enter' || e.key === ' ') {
				e.preventDefault();
				filtersOpen = !filtersOpen;
			}
		}}
	>
		<i class="bi bi-chevron-{filtersOpen ? 'down' : 'right'} me-2"></i>
		Filters <span class="text-body-secondary small ms-1">(transient — applied to this run only)</span>
	</div>
	{#if filtersOpen}
	<div class="card-body">
		{#if filters.length === 0 && typeFilters.length === 0}
			<p class="text-body-secondary small mb-2">
				No filters — the task runs on all (active) images.
			</p>
		{/if}
		{#each filters as f, i (i)}
			<div class="row g-2 mb-2 align-items-center">
				<div class="col-sm-4">
					<input class="form-control form-control-sm" placeholder="attribute" bind:value={f.attribute} />
				</div>
				<div class="col-sm-4">
					<input class="form-control form-control-sm" placeholder="value" bind:value={f.value} />
				</div>
				<div class="col-sm-2">
					<button class="btn btn-sm btn-outline-danger" onclick={() => removeFilter(i)} title="Remove filter">
						<i class="bi bi-trash"></i>
					</button>
				</div>
			</div>
		{/each}
		<button class="btn btn-sm btn-outline-secondary" onclick={addFilter}>
			<i class="bi bi-plus-lg"></i> Add filter
		</button>

		<div class="mt-3">
				<h6 class="small fw-semibold">Type filters</h6>
				{#each typeFilters as f, i (i)}
					<div class="row g-2 mb-2 align-items-center">
						<div class="col-sm-4">
							<input class="form-control form-control-sm" placeholder="type (e.g. is_3D)" bind:value={f.key} />
						</div>
						<div class="col-sm-4">
							<select class="form-select form-select-sm" bind:value={f.value}>
								<option value={true}>true</option>
								<option value={false}>false</option>
							</select>
						</div>
						<div class="col-sm-2">
							<button class="btn btn-sm btn-outline-danger" onclick={() => removeTypeFilter(i)} title="Remove type filter">
								<i class="bi bi-trash"></i>
							</button>
						</div>
					</div>
				{/each}
				<button class="btn btn-sm btn-outline-secondary" onclick={addTypeFilter}>
					<i class="bi bi-plus-lg"></i> Add type filter
				</button>
			</div>

			<hr />
		<h6 class="small fw-semibold">Images this task will run on</h6>
		{#if !preview}
			<p class="text-body-secondary small mb-0">No dataset loaded.</p>
		{:else if preview.is_converter}
			<p class="small mb-0">
				Converter task: runs on <code>{preview.zarr_dir}</code>; existing images are ignored.
			</p>
		{:else}
			<p class="small mb-1">{preview.n_visible} image(s) will be processed:</p>
			{#if preview.visible_urls.length === 0}
				<p class="text-body-secondary small mb-0">(none)</p>
			{:else}
				<div style="max-height: 10rem; overflow:auto;" class="font-monospace small">
					{#each preview.visible_urls as url (url)}
						<div class="text-break">{url}</div>
					{/each}
				</div>
			{/if}
		{/if}
	</div>
	{/if}
</div>

<!-- Task & parameters -->
<div class="card mb-3">
	<div class="card-header">Task &amp; parameters</div>
	<div class="card-body">
		<label class="form-label" for="task-select">Select a task</label>
		<TaskFilters tasks={store.tasks} bind:filtered={filteredTasks} />
		<select id="task-select" class="form-select mb-3" bind:value={selectedName} onchange={onSelectTask}>
			<option value="" disabled>— choose a task —</option>
			{#each filteredTasks as t (t.unique_id)}
				<option value={t.unique_id}>{t.unique_id}</option>
			{/each}
		</select>

		{#each phases as p (p.phase)}
			<h6 class="mt-3 text-uppercase text-body-secondary">{p.phase.replace('_', '-')} arguments</h6>
			<div use:enhancePathFields>
				<JSchema
					bind:this={formRefs[p.phase]}
					schemaVersion="pydantic_v2"
					componentId={`args-${p.phase}`}
					editable={true}
					propertiesToIgnore={HIDDEN[p.phase]}
					bind:dataValid={formValid[p.phase]}
					onchange={() => {}}
				/>
			</div>
		{/each}
	</div>
</div>

<!-- Run controls -->
<div class="d-flex flex-wrap align-items-end gap-3 mb-3">
	{#if running}
		<button class="btn btn-danger" onclick={cancel}>
			<i class="bi bi-stop-fill"></i> Cancel
		</button>
		<div class="spinner-border text-primary" role="status"><span class="visually-hidden">Running…</span></div>
	{:else}
		<button class="btn btn-success" onclick={run} disabled={!selectedTask || !store.dataset || !allValid}>
			<i class="bi bi-play-fill"></i> Run
		</button>
	{/if}
	<div>
		<label class="form-label small mb-0" for="max-workers">Workers</label>
		<input id="max-workers" type="number" min="1" step="1" class="form-control form-control-sm" style="width: 6rem;" bind:value={maxWorkers} />
	</div>
	<button class="btn btn-sm btn-outline-secondary" onclick={doExport}>
		<i class="bi bi-download"></i> Export params
	</button>
	<button class="btn btn-sm btn-outline-secondary" onclick={doImport}>
		<i class="bi bi-upload"></i> Import params
	</button>
</div>

<!-- Output: Log <-> Dataset -->
<div class="card mb-3">
	<div class="card-header d-flex align-items-center justify-content-between">
		<span>Output</span>
		<div class="btn-group btn-group-sm" role="group">
			<button class="btn {view === 'log' ? 'btn-secondary' : 'btn-outline-secondary'}" onclick={() => (view = 'log')}>Log</button>
			<button class="btn {view === 'dataset' ? 'btn-secondary' : 'btn-outline-secondary'}" onclick={() => (view = 'dataset')}>Dataset</button>
		</div>
	</div>
	<div class="card-body">
		{#if summary}
			<p class="fw-bold mb-2">
				{summary}
				{#if metrics?.total_seconds != null}
					<span class="text-body-secondary fw-normal small ms-2">
						· {metrics.total_seconds.toFixed(1)}s total{#if metrics.mean_item_seconds != null}, {metrics.mean_item_seconds.toFixed(1)}s avg/image{/if}
					</span>
				{/if}
			</p>
		{/if}
		{#if view === 'log'}
			<pre class="border rounded bg-body-tertiary p-2 mb-0" style="height: 18rem; overflow:auto;">{logLines.join('\n')}</pre>
		{:else}
			<DatasetTable dataset={store.dataset} />
		{/if}
	</div>
</div>

<!-- Run history -->
<div class="card mb-3">
	<div class="card-header">Run history (this session)</div>
	<div class="card-body">
		{#if history.length === 0}
			<p class="text-body-secondary mb-0">No runs yet this session.</p>
		{:else}
			<div class="accordion" id="run-history">
				{#each [...history].reverse() as rec (rec.index)}
					<div class="accordion-item">
						<h2 class="accordion-header">
							<button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target={`#hist-${rec.index}`}>
								<i class="bi {statusIcon(rec.status)} me-1 flex-shrink-0"></i>
								<span class="text-truncate" style="min-width: 0;">#{rec.index} {rec.task_name} — {rec.summary}</span>
							</button>
						</h2>
						<div id={`hist-${rec.index}`} class="accordion-collapse collapse" data-bs-parent="#run-history">
							<div class="accordion-body">
								<button class="btn btn-sm btn-outline-primary mb-2" onclick={() => restore(rec)}>
									<i class="bi bi-arrow-counterclockwise"></i> Restore
								</button>
								{#if rec.status === 'failed'}
									<p class="small text-danger mb-2"><i class="bi bi-exclamation-triangle me-1"></i>{rec.summary}</p>
								{/if}
								{#if rec.filters?.length}
									<p class="small mb-1">Filters: {rec.filters.map(([a, v]) => `${a} == ${JSON.stringify(v)}`).join(', ')}</p>
								{:else}
									<p class="small text-body-secondary mb-1">Filters: none</p>
								{/if}
								{#if rec.type_filters?.length}
									<p class="small mb-1">Type filters: {rec.type_filters.map(([k, v]) => `${k} == ${v}`).join(', ')}</p>
								{/if}
								<pre class="small bg-body-secondary p-2 rounded mb-0">{JSON.stringify({ kwargs_non_parallel: rec.kwargs_non_parallel, kwargs_parallel: rec.kwargs_parallel }, null, 2)}</pre>
							</div>
						</div>
					</div>
				{/each}
			</div>
		{/if}
	</div>
</div>
