import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import { fileURLToPath, URL } from 'node:url';

// Vendor the JSchema form renderer by aliasing `fractal-components` straight to the
// source of the local fractal-web clone, pinned at tag v1.29.10 (the brief's §6,
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
	plugins: [
		sveltekit({
			preprocess: vitePreprocess(),
			// Single-user local app: build a static SPA, served by FastAPI. The fallback
			// lets the client router handle every route (no SSR/prerender needed).
			adapter: adapter({ fallback: 'index.html' })
		})
	],
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
