<script>
	// Reusable task-list filter: a free-text name search plus faceted dropdowns
	// auto-populated from the distinct values present in the task list. The
	// filtered result is exposed via the bindable `filtered` prop.
	let { tasks = [], filtered = $bindable([]) } = $props();

	let search = $state('');
	let category = $state('');
	let modality = $state('');
	let pkg = $state('');
	let tag = $state('');

	function uniq(values) {
		return [...new Set(values.filter((v) => v != null && v !== ''))].sort();
	}

	const categories = $derived(uniq(tasks.map((t) => t.category)));
	const modalities = $derived(uniq(tasks.map((t) => t.modality)));
	const packages = $derived(uniq(tasks.map((t) => t.package)));
	const allTags = $derived(uniq(tasks.flatMap((t) => t.tags ?? [])));

	const result = $derived(
		tasks.filter((t) => {
			if (search && !t.name.toLowerCase().includes(search.toLowerCase())) return false;
			if (category && t.category !== category) return false;
			if (modality && t.modality !== modality) return false;
			if (pkg && t.package !== pkg) return false;
			if (tag && !(t.tags ?? []).includes(tag)) return false;
			return true;
		})
	);

	$effect(() => {
		filtered = result;
	});
</script>

<div class="row g-2 mb-2">
	<div class="col-sm-4">
		<input
			class="form-control form-control-sm"
			type="search"
			placeholder="Search name…"
			bind:value={search}
		/>
	</div>
	<div class="col-sm-2">
		<select class="form-select form-select-sm" bind:value={category} aria-label="Category">
			<option value="">All categories</option>
			{#each categories as c (c)}
				<option value={c}>{c}</option>
			{/each}
		</select>
	</div>
	<div class="col-sm-2">
		<select class="form-select form-select-sm" bind:value={modality} aria-label="Modality">
			<option value="">All modalities</option>
			{#each modalities as m (m)}
				<option value={m}>{m}</option>
			{/each}
		</select>
	</div>
	<div class="col-sm-2">
		<select class="form-select form-select-sm" bind:value={pkg} aria-label="Package">
			<option value="">All packages</option>
			{#each packages as p (p)}
				<option value={p}>{p}</option>
			{/each}
		</select>
	</div>
	<div class="col-sm-2">
		<select class="form-select form-select-sm" bind:value={tag} aria-label="Tag">
			<option value="">All tags</option>
			{#each allTags as t (t)}
				<option value={t}>{t}</option>
			{/each}
		</select>
	</div>
</div>
