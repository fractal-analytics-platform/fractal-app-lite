<script>
	import { onMount } from 'svelte';
	import {
		collectTasks,
		collectGitRelease,
		getPackageIndex,
		getTaskDetails,
		saveRegistry,
		loadRegistry
	} from '$lib/api.js';
	import { store, notify } from '$lib/stores.svelte.js';
	import { renderMarkdown } from '$lib/markdown.js';
	import { pickOpenDirectory, pickOpenFile, pickSaveFile } from '$lib/filepick.js';
	import TaskFilters from '$lib/components/TaskFilters.svelte';

	let selectedName = $state(null); // selected task's unique_id
	let filteredTasks = $state([]);
	let details = $state(null);
	let busy = $state(false);
	let gitModalOpen = $state(false);
	let repoUrl = $state('');
	let releaseTag = $state('');
	let packageIndex = $state([]); // curated git-release packages for the dropdown
	let selectedPackage = $state(''); // repo_url of the chosen curated package ('' = custom)

	onMount(async () => {
		try {
			packageIndex = await getPackageIndex();
		} catch (e) {
			notify(`Failed to load package list: ${e.message ?? e}`, 'negative');
		}
	});

	function applyPackage() {
		const entry = packageIndex.find((p) => p.repo_url === selectedPackage);
		if (!entry) return;
		repoUrl = entry.repo_url;
		releaseTag = entry.tag ?? '';
	}

	async function showDetails(uniqueId) {
		selectedName = uniqueId;
		details = null;
		try {
			details = await getTaskDetails(uniqueId);
		} catch (e) {
			notify(String(e.message ?? e), 'negative');
		}
	}

	async function registerDirectory() {
		const path = await pickOpenDirectory('Select task package directory');
		if (!path) return;
		busy = true;
		try {
			store.tasks = await collectTasks({ kind: 'directory', path });
			notify('Registered tasks from directory', 'positive');
		} catch (e) {
			notify(`Failed to register: ${e.message ?? e}`, 'negative');
		} finally {
			busy = false;
		}
	}

	async function registerTarball() {
		const path = await pickOpenFile('Select task tarball', [
			'Tarball (*.tar.gz;*.tgz;*.gz)',
			'All files (*.*)'
		]);
		if (!path) return;
		busy = true;
		try {
			store.tasks = await collectTasks({ kind: 'targz', path });
			notify('Registered tasks from tarball', 'positive');
		} catch (e) {
			notify(`Failed to register: ${e.message ?? e}`, 'negative');
		} finally {
			busy = false;
		}
	}

	function openGitReleaseModal() {
		repoUrl = '';
		releaseTag = '';
		selectedPackage = '';
		gitModalOpen = true;
	}

	async function registerGitRelease(e) {
		e?.preventDefault();
		if (!repoUrl.trim()) return;
		busy = true;
		try {
			store.tasks = await collectGitRelease({
				repo_url: repoUrl.trim(),
				tag: releaseTag.trim() || null
			});
			gitModalOpen = false;
			notify('Registered tasks from git release', 'positive');
		} catch (err) {
			notify(`Failed to register: ${err.message ?? err}`, 'negative');
		} finally {
			busy = false;
		}
	}

	async function doSaveRegistry() {
		const path = await pickSaveFile('Save registry', 'registry.json', [
			'JSON (*.json)',
			'All files (*.*)'
		]);
		if (!path) return;
		busy = true;
		try {
			await saveRegistry(path);
			notify(`Saved registry to ${path}`, 'positive');
		} catch (e) {
			notify(`Failed to save: ${e.message ?? e}`, 'negative');
		} finally {
			busy = false;
		}
	}

	async function doLoadRegistry() {
		const path = await pickOpenFile('Load registry', ['JSON (*.json)', 'All files (*.*)']);
		if (!path) return;
		busy = true;
		try {
			store.tasks = await loadRegistry(path);
			selectedName = null;
			details = null;
			notify('Loaded registry', 'positive');
		} catch (e) {
			notify(`Failed to load: ${e.message ?? e}`, 'negative');
		} finally {
			busy = false;
		}
	}
</script>

<div class="card mb-3">
	<div class="card-header d-flex align-items-center justify-content-between">
		<span>Register tasks</span>
		<div class="btn-group btn-group-sm">
			<button class="btn btn-outline-secondary" onclick={doLoadRegistry} disabled={busy}>
				<i class="bi bi-upload"></i> Load registry
			</button>
			<button class="btn btn-outline-secondary" onclick={doSaveRegistry} disabled={busy}>
				<i class="bi bi-download"></i> Save registry
			</button>
		</div>
	</div>
	<div class="card-body d-flex gap-2">
		<button class="btn btn-primary" onclick={registerDirectory} disabled={busy}>
			<i class="bi bi-folder2"></i> Register directory
		</button>
		<button class="btn btn-primary" onclick={registerTarball} disabled={busy}>
			<i class="bi bi-file-zip"></i> Register tarball
		</button>
		<button class="btn btn-primary" onclick={openGitReleaseModal} disabled={busy}>
			<i class="bi bi-github"></i> Register git release
		</button>
	</div>
</div>

{#if gitModalOpen}
	<div class="modal d-block" tabindex="-1" style="background: rgba(0,0,0,.5);">
		<div class="modal-dialog modal-dialog-centered">
			<div class="modal-content">
				<form onsubmit={registerGitRelease}>
					<div class="modal-header">
						<h5 class="modal-title">Register from git release</h5>
						<button
							type="button"
							class="btn-close"
							aria-label="Close"
							onclick={() => (gitModalOpen = false)}
						></button>
					</div>
					<div class="modal-body">
						{#if packageIndex.length > 0}
							<div class="mb-3">
								<label class="form-label" for="gitrelease-package">Curated package</label>
								<select
									id="gitrelease-package"
									class="form-select"
									bind:value={selectedPackage}
									onchange={applyPackage}
								>
									<option value="">Custom (enter manually)…</option>
									{#each packageIndex as p (p.repo_url)}
										<option value={p.repo_url}>{p.name}</option>
									{/each}
								</select>
								{#if selectedPackage}
									{@const entry = packageIndex.find((p) => p.repo_url === selectedPackage)}
									{#if entry?.description}
										<div class="form-text">{entry.description}</div>
									{/if}
								{/if}
							</div>
						{/if}
						<div class="mb-3">
							<label class="form-label" for="gitrelease-repo">GitHub repository URL</label>
							<!-- svelte-ignore a11y_autofocus -->
							<input
								id="gitrelease-repo"
								class="form-control font-monospace"
								bind:value={repoUrl}
								autofocus
								placeholder="https://github.com/owner/repo"
							/>
						</div>
						<div>
							<label class="form-label" for="gitrelease-tag">Tag</label>
							<input
								id="gitrelease-tag"
								class="form-control font-monospace"
								bind:value={releaseTag}
								placeholder="latest"
							/>
							<div class="form-text">Leave blank to use the latest release.</div>
						</div>
					</div>
					<div class="modal-footer">
						<button
							type="button"
							class="btn btn-outline-secondary"
							onclick={() => (gitModalOpen = false)}
						>
							Cancel
						</button>
						<button type="submit" class="btn btn-primary" disabled={busy || !repoUrl.trim()}>
							Register
						</button>
					</div>
				</form>
			</div>
		</div>
	</div>
{/if}

<div class="card mb-3">
	<div class="card-header">Registered tasks</div>
	<div class="card-body">
		{#if store.tasks.length === 0}
			<p class="text-body-secondary mb-0">
				No tasks registered. Register from a directory or a tarball.
			</p>
		{:else}
			<TaskFilters tasks={store.tasks} bind:filtered={filteredTasks} />
			<div class="table-responsive">
				<table class="table table-sm table-hover align-middle mb-1">
					<thead>
						<tr>
							<th>Name</th><th>Package</th><th>Type</th><th>Modality</th><th>Category</th><th>Source</th>
						</tr>
					</thead>
					<tbody>
						{#each filteredTasks as t (t.unique_id)}
							<tr
								role="button"
								class={selectedName === t.unique_id ? 'table-active' : ''}
								onclick={() => showDetails(t.unique_id)}
							>
								<td>{t.name}</td>
								<td>{t.package}</td>
								<td>{t.type}</td>
								<td>{t.modality ?? ''}</td>
								<td>{t.category ?? ''}</td>
								<td class="small text-break font-monospace">{t.source ?? ''}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
			<p class="form-text mb-0">
				{store.tasks.length} task(s) registered — click a row to view its docs and schemas.
			</p>
		{/if}
	</div>
</div>

<div class="card mb-3">
	<div class="card-header">Task details</div>
	<div class="card-body">
		{#if !selectedName}
			<p class="text-body-secondary mb-0">Select a task to view its docs and argument schemas.</p>
		{:else if !details}
			<p class="text-body-secondary mb-0">Loading…</p>
		{:else}
			<h5>{details.name} <span class="text-body-secondary fw-normal">[{details.package}]</span></h5>
			<p class="small text-body-secondary">
				{details.type}{details.modality ? ` · ${details.modality}` : ''}{details.category
					? ` · ${details.category}`
					: ''}
			</p>
			{#if details.docs_info}
				<!-- eslint-disable-next-line svelte/no-at-html-tags -->
				<div class="mb-3">{@html renderMarkdown(details.docs_info)}</div>
			{/if}
			{#if details.args_schema_non_parallel}
				<details class="mb-2">
					<summary>args_schema_non_parallel</summary>
					<pre class="small bg-body-secondary p-2 rounded mt-1">{JSON.stringify(
							details.args_schema_non_parallel,
							null,
							2
						)}</pre>
				</details>
			{/if}
			{#if details.args_schema_parallel}
				<details class="mb-2">
					<summary>args_schema_parallel</summary>
					<pre class="small bg-body-secondary p-2 rounded mt-1">{JSON.stringify(
							details.args_schema_parallel,
							null,
							2
						)}</pre>
				</details>
			{/if}
		{/if}
	</div>
</div>
