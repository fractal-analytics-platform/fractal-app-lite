// Render a task's `docs_info` markdown to sanitized HTML. marked + dompurify are
// already bundled (they back the JSchema renderer), so this adds no new dependency.

import { marked } from 'marked';
import DOMPurify from 'dompurify';

export function renderMarkdown(src) {
	if (!src) return '';
	const html = marked.parse(src, { async: false });
	return DOMPurify.sanitize(html);
}
