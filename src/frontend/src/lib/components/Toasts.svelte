<script>
	import { toasts, dismissToast } from '$lib/stores.svelte.js';

	const CLASS = {
		info: 'text-bg-secondary',
		positive: 'text-bg-success',
		success: 'text-bg-success',
		warning: 'text-bg-warning',
		negative: 'text-bg-danger',
		error: 'text-bg-danger'
	};
</script>

<div class="toast-container position-fixed top-0 end-0 p-3" style="z-index: 1090;">
	{#each toasts.items as t (t.id)}
		<div class="toast show align-items-center border-0 mb-2 {CLASS[t.type] ?? CLASS.info}">
			<div class="d-flex">
				<div class="toast-body">{t.message}</div>
				<button
					type="button"
					class="btn-close btn-close-white me-2 m-auto"
					aria-label="Close"
					onclick={() => dismissToast(t.id)}
				></button>
			</div>
		</div>
	{/each}
</div>
