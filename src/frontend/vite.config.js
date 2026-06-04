import { sveltekit } from '@sveltejs/kit/vite';
import { fileURLToPath, URL } from 'node:url';

// Vendor the JSchema form renderer by aliasing `fractal-components` straight to the
// source of the local fractal-web clone, pinned at tag v1.27.11 (the brief's §6,
// integration #2). The components are not pre-built; vite-plugin-svelte compiles their
// .svelte sources, and their runtime deps (ajv, dompurify, marked, ...) resolve from
// this project's node_modules.
const fractalComponents = fileURLToPath(
	new URL('../../fractal-web-clone/components/src/lib/index.js', import.meta.url)
);
const fractalComponentsRoot = fileURLToPath(
	new URL('../../fractal-web-clone', import.meta.url)
);

export default {
	plugins: [sveltekit()],
	resolve: {
		alias: {
			'fractal-components': fractalComponents
		}
	},
	server: {
		fs: {
			// Allow importing the aliased component source from outside the project.
			allow: ['..', fractalComponentsRoot]
		}
	}
};
