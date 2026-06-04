<script>
	// "New project" dialog: collect a project directory, name, description and zarr_dir,
	// then create the project on the backend. On success it calls `onCreated(info)` so the
	// layout can refresh every tab. Directory fields use the native picker (with a
	// typed-path fallback) exactly like the rest of the app.
	//
	// The zarr_dir defaults to a `zarr_dir` folder inside the project directory and tracks
	// it until the user edits the field by hand.
	import { newProject } from '$lib/api.js';
	import { notify } from '$lib/stores.svelte.js';
	import { pickOpenDirectory } from '$lib/filepick.js';

	let { open = $bindable(false), onCreated } = $props();

	let projectDir = $state('');
	let name = $state('Project');
	let description = $state('');
	let zarrDir = $state('');
	let zarrDirEdited = $state(false);
	let busy = $state(false);

	// Join an absolute dir with a child segment, honouring its path separator.
	function joinPath(dir, child) {
		if (!dir) return '';
		const sep = dir.includes('\\') && !dir.includes('/') ? '\\' : '/';
		return dir.replace(/[\\/]+$/, '') + sep + child;
	}

	function effectiveDir(dir) {
		if (!dir.trim()) return '';
		const t = dir.replace(/[\\/]+$/, '');
		return t.endsWith('.flp') ? t : t + '.flp';
	}

	// Keep zarr_dir defaulting to {project_dir}/zarr_dir until the user overrides it.
	$effect(() => {
		if (!zarrDirEdited) zarrDir = joinPath(effectiveDir(projectDir), 'zarr_dir');
	});

	function reset() {
		projectDir = '';
		name = 'Project';
		description = '';
		zarrDir = '';
		zarrDirEdited = false;
	}

	async function browseProjectDir() {
		const path = await pickOpenDirectory('Select project directory');
		if (path) projectDir = path;
	}

	async function browseZarrDir() {
		const path = await pickOpenDirectory('Select zarr_dir');
		if (path) {
			zarrDir = path;
			zarrDirEdited = true;
		}
	}

	function cancel() {
		open = false;
	}

	async function submit(e) {
		e?.preventDefault();
		if (!projectDir.trim()) {
			notify('Set a project directory first.', 'warning');
			return;
		}
		if (!zarrDir.trim()) {
			notify('Set a zarr_dir first.', 'warning');
			return;
		}
		busy = true;
		try {
			const info = await newProject({
				project_dir: projectDir,
				name: name || 'Project',
				description,
				zarr_dir: zarrDir
			});
			notify(`Created project '${info.name}' at ${info.project_dir}`, 'positive');
			open = false;
			reset();
			onCreated?.(info);
		} catch (err) {
			notify(String(err.message ?? err), 'negative');
		} finally {
			busy = false;
		}
	}
</script>

{#if open}
	<div class="modal d-block" tabindex="-1" style="background: rgba(0,0,0,.5);">
		<div class="modal-dialog modal-dialog-centered">
			<div class="modal-content">
				<form onsubmit={submit}>
					<div class="modal-header">
						<h5 class="modal-title">New project</h5>
						<button type="button" class="btn-close" aria-label="Close" onclick={cancel}></button>
					</div>
					<div class="modal-body">
						<div class="mb-3">
							<label class="form-label" for="np-name">Name</label>
							<input id="np-name" class="form-control" bind:value={name} />
						</div>
						<div class="mb-3">
							<label class="form-label" for="np-desc">Description</label>
							<textarea
								id="np-desc"
								class="form-control"
								rows="2"
								bind:value={description}
								placeholder="Optional notes about this project"
							></textarea>
						</div>
						<div class="mb-3">
							<label class="form-label" for="np-dir">Project directory</label>
							<div class="input-group">
								<input
									id="np-dir"
									class="form-control"
									bind:value={projectDir}
									placeholder="/abs/path/to/project"
								/>
								<button
									type="button"
									class="btn btn-outline-secondary"
									onclick={browseProjectDir}
									title="Browse…"
								>
									<i class="bi bi-folder2-open"></i>
								</button>
							</div>
							{#if projectDir.trim()}
								<p class="form-text mb-0">
									Will be created as: <code>{effectiveDir(projectDir)}</code>
								</p>
							{:else}
								<p class="form-text mb-0">
									A new or existing empty directory. The <code>.flp</code> extension is added
									automatically.
								</p>
							{/if}
						</div>
						<div class="mb-2">
							<label class="form-label" for="np-zarr">zarr_dir</label>
							<div class="input-group">
								<input
									id="np-zarr"
									class="form-control"
									bind:value={zarrDir}
									oninput={() => (zarrDirEdited = true)}
									placeholder="/abs/path/to/output_zarr"
								/>
								<button
									type="button"
									class="btn btn-outline-secondary"
									onclick={browseZarrDir}
									title="Browse…"
								>
									<i class="bi bi-folder2-open"></i>
								</button>
							</div>
							<p class="form-text mb-0">
								Created on disk so tasks have somewhere to write. Defaults to a
								<code>zarr_dir</code> folder inside the project.
							</p>
						</div>
					</div>
					<div class="modal-footer">
						<button type="button" class="btn btn-outline-secondary" onclick={cancel}>Cancel</button>
						<button type="submit" class="btn btn-primary" disabled={busy}>Create</button>
					</div>
				</form>
			</div>
		</div>
	</div>
{/if}
