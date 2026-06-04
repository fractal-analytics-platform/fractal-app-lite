import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	preprocess: vitePreprocess(),
	kit: {
		// Single-user local app: build a static SPA, served by FastAPI. The fallback
		// lets the client router handle every route (no SSR/prerender needed).
		adapter: adapter({ fallback: 'index.html' })
	}
};

export default config;
