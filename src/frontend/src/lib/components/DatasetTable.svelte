<script>
	// Read-only image table: zarr_url, hidden badge, dynamic attribute columns, image +
	// hidden counts, client-side quick-search, pagination, and per-row open-in-napari.
	import { openInNapari } from '$lib/api.js';
	import { notify } from '$lib/stores.svelte.js';

	let { dataset = null, pageSize = 25, onRemove = null } = $props();

	let search = $state('');
	let page = $state(0);

	const zarrUrls = $derived(dataset?.zarr_urls ?? []);

	// Attributes and types are merged for display (types are shown as columns too).
	function merged(zu) {
		return { ...(zu.attributes ?? {}), ...(zu.types ?? {}) };
	}

	// Union of attribute + type keys across all images, preserving first-seen order.
	const attrKeys = $derived.by(() => {
		const keys = [];
		for (const zu of zarrUrls) {
			for (const k of Object.keys(merged(zu))) {
				if (!keys.includes(k)) keys.push(k);
			}
		}
		return keys;
	});

	const nHidden = $derived(zarrUrls.filter((zu) => zu.hidden).length);

	const filtered = $derived.by(() => {
		const q = search.trim().toLowerCase();
		if (!q) return zarrUrls;
		return zarrUrls.filter((zu) => {
			if (zu.url.toLowerCase().includes(q)) return true;
			return Object.values(merged(zu)).some((v) =>
				String(v).toLowerCase().includes(q)
			);
		});
	});

	const pageCount = $derived(Math.max(1, Math.ceil(filtered.length / pageSize)));
	// Clamp the current page whenever the filtered set shrinks.
	$effect(() => {
		if (page > pageCount - 1) page = pageCount - 1;
		if (page < 0) page = 0;
	});
	const pageRows = $derived(filtered.slice(page * pageSize, page * pageSize + pageSize));

	async function napari(url) {
		try {
			await openInNapari(url);
			notify(`Opening in napari: ${url}`, 'positive');
		} catch (e) {
			notify(String(e.message ?? e), 'negative');
		}
	}

	function cell(zu, key) {
		const v = merged(zu)[key];
		return v === undefined || v === null ? '' : String(v);
	}
</script>

{#if !dataset}
	<p class="text-body-secondary mb-0">No dataset loaded.</p>
{:else}
	<div class="d-flex flex-wrap gap-3 align-items-center mb-2">
		<span class="text-body-secondary small">
			<strong>{dataset.name}</strong> — <code>{dataset.zarr_dir}</code>
		</span>
		<span class="badge text-bg-light">{zarrUrls.length} image(s)</span>
		<span class="badge text-bg-light">{nHidden} hidden</span>
		<input
			class="form-control form-control-sm ms-auto"
			style="max-width: 16rem;"
			placeholder="Quick search…"
			bind:value={search}
		/>
	</div>

	<div class="table-responsive">
		<table class="table table-sm table-hover align-middle">
			<thead>
				<tr>
					<th style="width: 3rem;"></th>
					<th>zarr_url</th>
					<th class="text-center">hidden</th>
					{#each attrKeys as k (k)}
						<th>{k}</th>
					{/each}
					{#if onRemove}
						<th style="width: 3rem;"></th>
					{/if}
				</tr>
			</thead>
			<tbody>
				{#each pageRows as zu (zu.url)}
					<tr>
						<td class="text-center">
							<button
								class="btn btn-sm btn-link p-0"
								title="Open in napari"
								aria-label="Open in napari"
								onclick={() => napari(zu.url)}
							>
								<i class="bi bi-box-arrow-up-right"></i>
							</button>
						</td>
						<td class="font-monospace small text-break">{zu.url}</td>
						<td class="text-center">
							<span class="badge {zu.hidden ? 'text-bg-danger' : 'text-bg-success'}">
								{zu.hidden}
							</span>
						</td>
						{#each attrKeys as k (k)}
							<td class="small">{cell(zu, k)}</td>
						{/each}
						{#if onRemove}
							<td class="text-center">
								<button
									class="btn btn-sm btn-link link-danger p-0"
									title="Remove image"
									aria-label="Remove image"
									onclick={() => onRemove(zu.url)}
								>
									<i class="bi bi-trash"></i>
								</button>
							</td>
						{/if}
					</tr>
				{:else}
					<tr>
						<td
							colspan={3 + attrKeys.length + (onRemove ? 1 : 0)}
							class="text-body-secondary text-center"
						>
							No matching images.
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>

	{#if pageCount > 1}
		<div class="d-flex align-items-center gap-2">
			<button
				class="btn btn-sm btn-outline-secondary"
				disabled={page === 0}
				onclick={() => (page -= 1)}>‹ Prev</button
			>
			<span class="small text-body-secondary">Page {page + 1} / {pageCount}</span>
			<button
				class="btn btn-sm btn-outline-secondary"
				disabled={page >= pageCount - 1}
				onclick={() => (page += 1)}>Next ›</button
			>
		</div>
	{/if}
{/if}
