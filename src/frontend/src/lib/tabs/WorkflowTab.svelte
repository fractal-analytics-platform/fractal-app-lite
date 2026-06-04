<script>
	import { tick } from 'svelte';
	import { JSchema, stripNullAndEmptyObjectsAndArrays } from 'fractal-components';
	import DatasetTable from '$lib/components/DatasetTable.svelte';
	import TaskFilters from '$lib/components/TaskFilters.svelte';
	import {
		getTaskSchema,
		getWorkflow,
		setWorkflow,
		runWorkflow,
		cancelRun,
		exportWorkflowFractal,
		importWorkflowFractal,
		listWorkflowHistory
	} from '$lib/api.js';
	import { connectRunSocket } from '$lib/ws.js';
	import { store, notify } from '$lib/stores.svelte.js';
	import { pickOpenFile, pickSaveFile } from '$lib/filepick.js';
	import { enhancePathFields } from '$lib/pathfield.js';

	// Args each task's run injects itself, hidden from the forms (mirrors SandboxTab).
	const HIDDEN = {
		non_parallel: ['zarr_dir', 'zarr_urls'],
		parallel: ['zarr_url', 'init_args']
	};

	// Workflow being edited. `steps` items match the backend WorkflowStep shape:
	//  task   -> { kind:'task', task_name, kwargs_non_parallel, kwargs_parallel }
	//  filter -> { kind:'filter', filter_type:'attribute', attribute, value }
	//         -> { kind:'filter', filter_type:'type', key, value }
	let name = $state('Unnamed Workflow');
	let description = $state('');
	let steps = $state([]);
	let selectedIndex = $state(null);

	// Editor state for the currently-selected *task* step (Sandbox-style JSchema forms).
	let filteredTasks = $state([]); // narrowed task list for the "add task" picker
	let addTaskName = $state(''); // unique_id chosen in the picker
	let addTaskModalOpen = $state(false);
	let phases = $state([]); // [{ phase, schema }]
	let formRefs = $state({}); // phase -> JSchema instance
	let formValid = $state({}); // phase -> boolean

	// Run state.
	let maxWorkers = $state(1);
	let runFirst = $state(0); // inclusive start index
	let runLast = $state(/** @type {number | null} */ (null)); // inclusive end index; null tracks "last step"
	let running = $state(false);
	let jobId = $state(null);
	let socket = null;
	let logLines = $state([]);
	let summary = $state('');
	let metrics = $state(null);
	let view = $state('log'); // 'log' | 'dataset'

	// Past workflow runs (restore-capable history; mirrors SandboxTab).
	let history = $state([]);

	const selectedStep = $derived(selectedIndex == null ? null : steps[selectedIndex] ?? null);

	// Keep the run range valid as steps change: clamp both indices in bounds, default
	// "Last step" to the final step, and ensure Last step >= First step.
	$effect(() => {
		if (steps.length === 0) return;
		const max = steps.length - 1;
		if (runFirst > max) runFirst = max;
		if (runLast == null || runLast > max) runLast = max;
		if (runLast < runFirst) runLast = runFirst;
	});

	function stepLabel(step) {
		if (step.kind === 'task') return step.task_name;
		if (step.filter_type === 'attribute')
			return `filter: ${step.attribute || '?'} == ${step.value ?? '?'}`;
		return `type: ${step.key || '?'} == ${step.value}`;
	}

	function stepIcon(step) {
		if (step.kind === 'task') return 'bi-box';
		return 'bi-funnel';
	}

	function statusIcon(status) {
		if (status === 'cancelled') return 'bi-slash-circle-fill text-warning';
		if (status === 'failed') return 'bi-x-circle-fill text-danger';
		return 'bi-check-circle-fill text-success';
	}

	// --- Editor sync ------------------------------------------------------- //

	// Read the live JSchema forms back into the selected task step.
	function syncSelectedStep() {
		const step = selectedStep;
		if (!step || step.kind !== 'task') return;
		for (const { phase } of phases) {
			const ref = formRefs[phase];
			if (!ref) continue;
			const args = stripNullAndEmptyObjectsAndArrays(ref.getArguments());
			step[`kwargs_${phase}`] = Object.keys(args).length ? args : null;
		}
	}

	// Load JSchema forms for a task step, seeded with its stored kwargs.
	async function loadTaskEditor(step) {
		phases = [];
		formRefs = {};
		formValid = {};
		const summaryRow = store.tasks.find((t) => t.unique_id === step.task_name);
		if (!summaryRow) {
			notify(`Task ${step.task_name} is not registered.`, 'warning');
			return;
		}
		const wanted = [];
		if (summaryRow.has_non_parallel) wanted.push('non_parallel');
		if (summaryRow.has_parallel) wanted.push('parallel');
		try {
			const loaded = [];
			for (const phase of wanted) {
				const res = await getTaskSchema(step.task_name, phase);
				loaded.push({ phase, schema: res.json_schema });
			}
			phases = loaded;
			await tick();
			const seed = {
				non_parallel: step.kwargs_non_parallel ?? undefined,
				parallel: step.kwargs_parallel ?? undefined
			};
			for (const { phase, schema } of phases) {
				formRefs[phase]?.update(schema, seed[phase]);
			}
		} catch (e) {
			notify(String(e.message ?? e), 'negative');
		}
	}

	async function selectStep(i) {
		if (i === selectedIndex) return;
		syncSelectedStep(); // capture the step we're leaving
		selectedIndex = i;
		phases = [];
		formRefs = {};
		formValid = {};
		const step = steps[i];
		if (step?.kind === 'task') await loadTaskEditor(step);
	}

	// --- Step list mutations ----------------------------------------------- //

	function openAddTaskModal() {
		addTaskName = '';
		addTaskModalOpen = true;
	}

	async function addTask() {
		if (!addTaskName) return;
		syncSelectedStep();
		steps.push({
			kind: 'task',
			task_name: addTaskName,
			kwargs_non_parallel: null,
			kwargs_parallel: null
		});
		addTaskName = '';
		addTaskModalOpen = false;
		await selectStepForced(steps.length - 1);
	}

	async function addFilter(filterType) {
		syncSelectedStep();
		const step =
			filterType === 'attribute'
				? { kind: 'filter', filter_type: 'attribute', attribute: '', value: '' }
				: { kind: 'filter', filter_type: 'type', key: '', value: true };
		steps.push(step);
		await selectStepForced(steps.length - 1);
	}

	// Like selectStep but always reloads (used after pushing a new step at i).
	async function selectStepForced(i) {
		selectedIndex = i;
		phases = [];
		formRefs = {};
		formValid = {};
		const step = steps[i];
		if (step?.kind === 'task') await loadTaskEditor(step);
	}

	function removeStep(i) {
		steps.splice(i, 1);
		if (steps.length === 0) {
			selectedIndex = null;
			phases = [];
			formRefs = {};
		} else {
			const next = Math.min(i, steps.length - 1);
			selectStepForced(next);
		}
	}

	function move(i, delta) {
		const j = i + delta;
		if (j < 0 || j >= steps.length) return;
		syncSelectedStep();
		const [moved] = steps.splice(i, 1);
		steps.splice(j, 0, moved);
		selectStepForced(j);
	}

	// --- Backend sync + payload -------------------------------------------- //

	function currentPayload() {
		syncSelectedStep();
		return { name, description: description || null, steps: $state.snapshot(steps) };
	}

	async function pushWorkflow() {
		await setWorkflow(currentPayload());
	}

	async function applyPayload(payload) {
		name = payload.name ?? 'Unnamed Workflow';
		description = payload.description ?? '';
		steps = (payload.steps ?? []).map((s) =>
			s.kind === 'task'
				? {
						kind: 'task',
						task_name: s.task_name,
						kwargs_non_parallel: s.kwargs_non_parallel ?? null,
						kwargs_parallel: s.kwargs_parallel ?? null
					}
				: s.filter_type === 'attribute'
					? { kind: 'filter', filter_type: 'attribute', attribute: s.attribute ?? '', value: s.value ?? '' }
					: { kind: 'filter', filter_type: 'type', key: s.key ?? '', value: !!s.value }
		);
		selectedIndex = null;
		phases = [];
		formRefs = {};
		if (steps.length) await selectStepForced(0);
	}

	// --- Run / cancel ------------------------------------------------------ //

	async function doRun(startTask, endTask) {
		if (!store.dataset) {
			notify('Create or load a dataset first.', 'warning');
			return;
		}
		if (steps.length === 0) {
			notify('Add at least one step.', 'warning');
			return;
		}
		logLines = [];
		summary = '';
		metrics = null;
		view = 'log';
		running = true;
		try {
			await pushWorkflow();
			const res = await runWorkflow({
				start_task: startTask,
				end_task: endTask,
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
						notify('Workflow completed.', 'positive');
					} else {
						notify('Workflow cancelled.', 'warning');
					}
					finishRun();
					refreshHistory();
				},
				onError: (msg) => {
					notify(msg.detail ?? 'Workflow run failed.', 'negative');
					logLines.push(`ERROR: ${msg.detail ?? 'Workflow run failed.'}`);
					finishRun();
					refreshHistory();
				}
			});
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

	async function refreshHistory() {
		try {
			history = await listWorkflowHistory();
		} catch {
			// non-fatal
		}
	}

	async function restore(rec) {
		if (!rec.payload) {
			notify('This run has no saved workflow to restore.', 'warning');
			return;
		}
		await applyPayload(rec.payload);
		await pushWorkflow();
		notify(`Restored workflow run #${rec.index}`, 'positive');
	}

	// --- Save / load / import / export ------------------------------------- //

	async function doExportFractal() {
		const path = await pickSaveFile('Export Fractal workflow', `${name}.json`, [
			'JSON (*.json)',
			'All files (*.*)'
		]);
		if (!path) return;
		try {
			await pushWorkflow();
			await exportWorkflowFractal(path);
			notify(`Exported (Fractal format) to ${path}`, 'positive');
		} catch (e) {
			notify(String(e.message ?? e), 'negative');
		}
	}

	async function doImportFractal() {
		const path = await pickOpenFile('Import Fractal workflow', [
			'JSON (*.json)',
			'All files (*.*)'
		]);
		if (!path) return;
		try {
			notify('Importing — may collect packages from GitHub…', 'info');
			const payload = await importWorkflowFractal(path);
			await applyPayload(payload);
			notify('Imported Fractal workflow', 'positive');
		} catch (e) {
			notify(String(e.message ?? e), 'negative');
		}
	}

	// Pull whatever the backend already holds (e.g. restored from a session).
	$effect(() => {
		(async () => {
			try {
				const payload = await getWorkflow();
				if (payload?.steps?.length) await applyPayload(payload);
			} catch {
				// non-fatal
			}
		})();
		refreshHistory();
	});
</script>

<!-- Workflow header: name, description, IO -->
<div class="card mb-3">
	<div class="card-body">
		<div class="row g-2 align-items-end">
			<div class="col-sm-4">
				<label class="form-label small mb-0" for="wf-name">Workflow name</label>
				<input id="wf-name" class="form-control form-control-sm" bind:value={name} />
			</div>
			<div class="col-sm-5">
				<label class="form-label small mb-0" for="wf-desc">Description</label>
				<input id="wf-desc" class="form-control form-control-sm" bind:value={description} placeholder="(optional)" />
			</div>
			<div class="col-sm-3 text-end">
				<div class="btn-group btn-group-sm" role="group">
					<button class="btn btn-outline-secondary" onclick={doExportFractal} title="Export to Fractal format (drops filters)">
						<i class="bi bi-box-arrow-up"></i> Export Fractal
					</button>
					<button class="btn btn-outline-secondary" onclick={doImportFractal} title="Import from Fractal format">
						<i class="bi bi-box-arrow-in-down"></i> Import Fractal
					</button>
				</div>
			</div>
		</div>
	</div>
</div>

<!-- Dataset banner + how the workflow treats the dataset -->
<div class="card mb-3">
	<div class="card-body py-2">
		{#if store.dataset}
			<span class="text-body-secondary small">
				Dataset: <strong>{store.dataset.name}</strong> —
				<code>{store.dataset.zarr_dir}</code> — {store.dataset.zarr_urls.length} image(s)
			</span>
		{:else}
			<span class="text-warning small">No dataset. Create or load one in the Dataset tab first.</span>
		{/if}
	</div>
</div>

<!-- Two-pane: step list | editor -->
<div class="row g-3 mb-3">
	<!-- Left: steps -->
	<div class="col-md-4">
		<div class="card h-100">
			<div class="card-header">Steps</div>
			<div class="card-body">
				{#if steps.length === 0}
					<p class="text-body-secondary small">No steps yet. Add a task or filter below.</p>
				{:else}
					<ol class="list-group list-group-numbered mb-3">
						{#each steps as step, i (i)}
							<li class="list-group-item d-flex align-items-center gap-2 {selectedIndex === i ? 'list-group-item-primary' : ''}">
								<button
									type="button"
									class="btn btn-link p-0 text-start text-decoration-none text-body flex-grow-1 text-truncate"
									style="min-width: 0;"
									onclick={() => selectStep(i)}
									title={stepLabel(step)}
								>
									<i class="bi {stepIcon(step)} me-1"></i>{stepLabel(step)}
								</button>
								<span class="btn-group btn-group-sm flex-shrink-0" role="group">
									<button class="btn btn-secondary py-0 px-1" disabled={i === 0} title="Move up"
										onclick={() => move(i, -1)}>
										<i class="bi bi-arrow-up"></i>
									</button>
									<button class="btn btn-secondary py-0 px-1" disabled={i === steps.length - 1} title="Move down"
										onclick={() => move(i, 1)}>
										<i class="bi bi-arrow-down"></i>
									</button>
									<button class="btn btn-danger py-0 px-1" title="Remove"
										onclick={() => removeStep(i)}>
										<i class="bi bi-trash"></i>
									</button>
								</span>
							</li>
						{/each}
					</ol>
				{/if}

				<div class="d-flex flex-wrap gap-2">
					<button class="btn btn-sm btn-outline-primary" onclick={openAddTaskModal}>
						<i class="bi bi-plus-lg"></i> Add task
					</button>
					<button class="btn btn-sm btn-outline-secondary" onclick={() => addFilter('attribute')}>
						<i class="bi bi-funnel"></i> Add attribute filter
					</button>
					<button class="btn btn-sm btn-outline-secondary" onclick={() => addFilter('type')}>
						<i class="bi bi-funnel"></i> Add type filter
					</button>
				</div>
			</div>
		</div>
	</div>

	<!-- Right: editor -->
	<div class="col-md-8">
		<div class="card h-100">
			<div class="card-header">
				{#if selectedStep}
					Step {selectedIndex + 1}: {stepLabel(selectedStep)}
				{:else}
					Step editor
				{/if}
			</div>
			<div class="card-body">
				{#if !selectedStep}
					<p class="text-body-secondary">Select a step to edit its parameters.</p>
				{:else if selectedStep.kind === 'task'}
					{#each phases as p (p.phase)}
						<h6 class="mt-3 text-uppercase text-body-secondary">{p.phase.replace('_', '-')} arguments</h6>
						<div use:enhancePathFields>
							<JSchema
								bind:this={formRefs[p.phase]}
								schemaVersion="pydantic_v2"
								componentId={`wf-args-${p.phase}`}
								editable={true}
								propertiesToIgnore={HIDDEN[p.phase]}
								bind:dataValid={formValid[p.phase]}
								onchange={() => {}}
							/>
						</div>
					{/each}
					{#if phases.length === 0}
						<p class="text-body-secondary small mb-0">This task exposes no editable arguments.</p>
					{/if}
				{:else if selectedStep.filter_type === 'attribute'}
					<div class="row g-2 align-items-end">
						<div class="col-sm-6">
							<label class="form-label small mb-0" for="flt-attr">Attribute</label>
							<input id="flt-attr" class="form-control form-control-sm" placeholder="e.g. well" bind:value={steps[selectedIndex].attribute} />
						</div>
						<div class="col-sm-6">
							<label class="form-label small mb-0" for="flt-val">Value (keeps images where attribute == value)</label>
							<input id="flt-val" class="form-control form-control-sm" bind:value={steps[selectedIndex].value} />
						</div>
					</div>
				{:else}
					<div class="row g-2 align-items-end">
						<div class="col-sm-6">
							<label class="form-label small mb-0" for="flt-key">Type key</label>
							<input id="flt-key" class="form-control form-control-sm" placeholder="e.g. is_3D" bind:value={steps[selectedIndex].key} />
						</div>
						<div class="col-sm-6">
							<label class="form-label small mb-0" for="flt-bool">Value</label>
							<select id="flt-bool" class="form-select form-select-sm" bind:value={steps[selectedIndex].value}>
								<option value={true}>true</option>
								<option value={false}>false</option>
							</select>
						</div>
					</div>
				{/if}
			</div>
		</div>
	</div>
</div>

<!-- Run controls -->
<div class="d-flex flex-wrap align-items-center gap-3 mb-3">
	{#if running}
		<button class="btn btn-danger" onclick={cancel}>
			<i class="bi bi-stop-fill"></i> Cancel
		</button>
		<div class="spinner-border text-primary" role="status"><span class="visually-hidden">Running…</span></div>
	{:else}
		<button class="btn btn-success" onclick={() => doRun(runFirst, (runLast ?? steps.length - 1) + 1)} disabled={!store.dataset || steps.length === 0}>
			<i class="bi bi-play-fill"></i> Run
		</button>
	{/if}
	<div class="input-group input-group-sm" style="width: auto;">
		<label class="input-group-text" for="wf-max-workers">Workers</label>
		<input id="wf-max-workers" type="number" min="1" step="1" class="form-control" style="width: 5rem;" bind:value={maxWorkers} />
	</div>
	{#if !running}
		<div class="input-group input-group-sm" style="width: auto; max-width: 14rem;">
			<span class="input-group-text" title="First step to run"><i class="bi bi-skip-start-fill"></i></span>
			<select class="form-select" aria-label="First step to run" bind:value={runFirst} disabled={steps.length === 0}>
				{#each steps as step, i (i)}
					<option value={i}>{i + 1}. {stepLabel(step)}</option>
				{/each}
			</select>
		</div>
		<div class="input-group input-group-sm" style="width: auto; max-width: 14rem;">
			<span class="input-group-text" title="Last step to run"><i class="bi bi-skip-end-fill"></i></span>
			<select class="form-select" aria-label="Last step to run" bind:value={runLast} disabled={steps.length === 0}>
				{#each steps as step, i (i)}
					{#if i >= runFirst}
						<option value={i}>{i + 1}. {stepLabel(step)}</option>
					{/if}
				{/each}
			</select>
		</div>
	{/if}
</div>

<!-- Output -->
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
					<span class="text-body-secondary fw-normal small ms-2">· {metrics.total_seconds.toFixed(1)}s total</span>
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
			<p class="text-body-secondary mb-0">No workflow runs yet this session.</p>
		{:else}
			<div class="accordion" id="wf-run-history">
				{#each [...history].reverse() as rec (rec.index)}
					<div class="accordion-item">
						<h2 class="accordion-header">
							<button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target={`#wf-hist-${rec.index}`}>
								<i class="bi {statusIcon(rec.status)} me-1 flex-shrink-0"></i>
								<span class="text-truncate" style="min-width: 0;">#{rec.index} {rec.name} — {rec.summary}</span>
							</button>
						</h2>
						<div id={`wf-hist-${rec.index}`} class="accordion-collapse collapse" data-bs-parent="#wf-run-history">
							<div class="accordion-body">
								<button class="btn btn-sm btn-outline-primary mb-2" onclick={() => restore(rec)} disabled={!rec.payload}>
									<i class="bi bi-arrow-counterclockwise"></i> Restore
								</button>
								{#if rec.status === 'failed'}
									<p class="small text-danger mb-2"><i class="bi bi-exclamation-triangle me-1"></i>{rec.summary}</p>
								{/if}
								<p class="small text-body-secondary mb-1">
									Ran steps {rec.start_task}–{rec.end_task ?? 'end'}
								</p>
								{#if rec.payload?.steps?.length}
									<ol class="small mb-0 ps-3">
										{#each rec.payload.steps as s, i (i)}
											<li><i class="bi {stepIcon(s)} me-1"></i>{stepLabel(s)}</li>
										{/each}
									</ol>
								{:else}
									<p class="small text-body-secondary mb-0">No steps recorded.</p>
								{/if}
							</div>
						</div>
					</div>
				{/each}
			</div>
		{/if}
	</div>
</div>

<!-- Add-task modal -->
{#if addTaskModalOpen}
	<div class="modal d-block" tabindex="-1" style="background: rgba(0,0,0,.5);">
		<div class="modal-dialog modal-dialog-centered modal-lg">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">Add task</h5>
					<button type="button" class="btn-close" aria-label="Close" onclick={() => (addTaskModalOpen = false)}></button>
				</div>
				<div class="modal-body">
					<TaskFilters tasks={store.tasks} bind:filtered={filteredTasks} />
					<select class="form-select" size="10" bind:value={addTaskName}>
						{#each filteredTasks as t (t.unique_id)}
							<option value={t.unique_id}>{t.unique_id}</option>
						{/each}
					</select>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-outline-secondary" onclick={() => (addTaskModalOpen = false)}>
						Cancel
					</button>
					<button type="button" class="btn btn-primary" onclick={addTask} disabled={!addTaskName}>
						<i class="bi bi-plus-lg"></i> Add to workflow
					</button>
				</div>
			</div>
		</div>
	</div>
{/if}
