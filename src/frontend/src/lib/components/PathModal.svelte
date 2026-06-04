<script>
	// Typed-path fallback dialog, shown only when no native OS dialog is available.
	import { pathModal, resolvePathModal } from '$lib/stores.svelte.js';

	function submit(e) {
		e?.preventDefault();
		resolvePathModal(pathModal.value);
	}
	function cancel() {
		resolvePathModal(null);
	}
</script>

{#if pathModal.open}
	<div class="modal d-block" tabindex="-1" style="background: rgba(0,0,0,.5);">
		<div class="modal-dialog modal-dialog-centered">
			<div class="modal-content">
				<form onsubmit={submit}>
					<div class="modal-header">
						<h5 class="modal-title">{pathModal.title}</h5>
						<button type="button" class="btn-close" aria-label="Close" onclick={cancel}
						></button>
					</div>
					<div class="modal-body">
						<label class="form-label" for="path-modal-input">Absolute path</label>
						<!-- svelte-ignore a11y_autofocus -->
						<input
							id="path-modal-input"
							class="form-control"
							bind:value={pathModal.value}
							autofocus
							placeholder="/absolute/path"
						/>
					</div>
					<div class="modal-footer">
						<button type="button" class="btn btn-outline-secondary" onclick={cancel}>
							Cancel
						</button>
						<button type="submit" class="btn btn-primary">OK</button>
					</div>
				</form>
			</div>
		</div>
	</div>
{/if}
