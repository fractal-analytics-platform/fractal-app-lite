<script>
	import { onMount } from 'svelte';
	import DatasetTab from '$lib/tabs/DatasetTab.svelte';
	import SandboxTab from '$lib/tabs/SandboxTab.svelte';
	import WorkflowTab from '$lib/tabs/WorkflowTab.svelte';
	import TasksTab from '$lib/tabs/TasksTab.svelte';
	import { listTasks } from '$lib/api.js';
	import { store, notify, refreshDataset } from '$lib/stores.svelte.js';

	const TABS = [
		{ id: 'dataset', label: 'Dataset', icon: 'bi-table' },
		{ id: 'sandbox', label: 'Tasks Sandbox', icon: 'bi-stack' },
		{ id: 'workflow', label: 'Workflow', icon: 'bi-diagram-2' },
		{ id: 'tasks', label: 'Task Management', icon: 'bi-diagram-3' }
	];
	let active = $state('dataset');

	onMount(async () => {
		try {
			store.tasks = await listTasks();
			await refreshDataset();
		} catch (e) {
			notify(String(e.message ?? e), 'negative');
		}
	});
</script>

<ul class="nav nav-tabs mb-3">
	{#each TABS as tab (tab.id)}
		<li class="nav-item">
			<button
				class="nav-link {active === tab.id ? 'active' : ''}"
				onclick={() => (active = tab.id)}
			>
				<i class="bi {tab.icon} me-1"></i>{tab.label}
			</button>
		</li>
	{/each}
</ul>

<!-- Keep tab bodies mounted so form/scroll state survives tab switches. -->
<div class:d-none={active !== 'dataset'}><DatasetTab /></div>
<div class:d-none={active !== 'sandbox'}><SandboxTab /></div>
<div class:d-none={active !== 'workflow'}><WorkflowTab /></div>
<div class:d-none={active !== 'tasks'}><TasksTab /></div>
