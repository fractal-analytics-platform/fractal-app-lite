// Thin fetch wrappers around the backend REST API. The frontend is served by the same
// FastAPI process, so requests are same-origin (relative URLs, no CORS).

async function request(path, options) {
	const res = await fetch(path, options);
	if (!res.ok) {
		let detail = res.statusText;
		try {
			const body = await res.json();
			detail = body.detail ?? detail;
		} catch {
			// non-JSON error body; keep statusText
		}
		throw new Error(detail);
	}
	return res.status === 204 ? null : res.json();
}

function post(path, body) {
	return request(path, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body ?? {})
	});
}

// --- Tasks ---------------------------------------------------------------- //

export function listTasks() {
	return request('/api/tasks');
}

export function getTaskSchema(name, phase) {
	const q = new URLSearchParams({ phase });
	return request(`/api/tasks/${encodeURIComponent(name)}/schema?${q}`);
}

export function getTaskDetails(name) {
	return request(`/api/tasks/${encodeURIComponent(name)}/details`);
}

export function collectTasks({ kind, path, overwrite = true }) {
	return post('/api/tasks/collect', { kind, path, overwrite });
}

export function collectGitRelease({ repo_url, tag, overwrite = true }) {
	return post('/api/tasks/collect', { kind: 'gitrelease', repo_url, tag, overwrite });
}

export function getPackageIndex() {
	return request('/api/tasks/package-index');
}

export function saveRegistry(path) {
	return post('/api/tasks/registry/save', { path });
}

export function loadRegistry(path) {
	return post('/api/tasks/registry/load', { path });
}

// --- Dataset -------------------------------------------------------------- //

export function getDataset() {
	return request('/api/dataset');
}

export function setDataset(dataset) {
	return post('/api/dataset', { dataset });
}

export function addDatasetStore(path) {
	return post('/api/dataset/add-store', { path });
}

export function removeDatasetStore(zarr_url) {
	return post('/api/dataset/remove-store', { zarr_url });
}

export function loadDatasetCsv(path) {
	return post('/api/dataset/load-csv', { path });
}

export function saveDatasetCsv(path) {
	return post('/api/dataset/save-csv', { path });
}

export function clearDatasetImages() {
	return post('/api/dataset/clear-images');
}

export function previewDataset(filters, type_filters = []) {
	return post('/api/dataset/preview', { filters, type_filters });
}

export function openInNapari(zarr_url) {
	return post('/api/dataset/napari', { zarr_url });
}

// --- Run ------------------------------------------------------------------ //

export function runTask(payload) {
	return post('/api/run', payload);
}

export function cancelRun(jobId) {
	return post(`/api/run/${encodeURIComponent(jobId)}/cancel`, {});
}

export function listHistory() {
	return request('/api/run/history');
}

// --- Params export / import ----------------------------------------------- //

export function exportParams({ path, kwargs_non_parallel, kwargs_parallel }) {
	return post('/api/params/export', { path, kwargs_non_parallel, kwargs_parallel });
}

export function importParams(path) {
	return post('/api/params/import', { path });
}

// --- Workflow ------------------------------------------------------------- //

export function getWorkflow() {
	return request('/api/workflow');
}

export function setWorkflow({ name, description, steps }) {
	return post('/api/workflow', { name, description, steps });
}

export function runWorkflow({ start_task = 0, end_task = null, max_workers = 1 } = {}) {
	return post('/api/workflow/run', { start_task, end_task, max_workers });
}

export function listWorkflowHistory() {
	return request('/api/workflow/history');
}

export function saveWorkflow(path) {
	return post('/api/workflow/save', { path });
}

export function loadWorkflow(path) {
	return post('/api/workflow/load', { path });
}

export function exportWorkflowFractal(path) {
	return post('/api/workflow/export-fractal', { path });
}

export function importWorkflowFractal(path) {
	return post('/api/workflow/import-fractal', { path });
}

// --- Project -------------------------------------------------------------- //

export function getProject() {
	return request('/api/project');
}

export function newProject({ project_dir, name, zarr_dir, description = '', max_workers = 1 }) {
	return post('/api/project/new', { project_dir, name, zarr_dir, description, max_workers });
}

export function openProject(project_dir) {
	return post('/api/project/open', { project_dir });
}

export function saveProject() {
	return post('/api/project/save', {});
}

// --- File-system dialogs -------------------------------------------------- //

export function fsOpenFile(file_types) {
	return post('/api/fs/open-file', { file_types });
}

export function fsOpenDirectory() {
	return post('/api/fs/open-directory', {});
}

export function fsSaveFile(default_name, file_types) {
	return post('/api/fs/save-file', { default_name, file_types });
}
