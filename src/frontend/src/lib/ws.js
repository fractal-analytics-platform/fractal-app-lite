// Connect to a run's live-log WebSocket. Resolves message frames to the supplied
// callbacks; returns the WebSocket so the caller can close it on teardown.

export function connectRunSocket(jobId, { onLog, onDone, onError } = {}) {
	const proto = location.protocol === 'https:' ? 'wss' : 'ws';
	const url = `${proto}://${location.host}/api/run/${encodeURIComponent(jobId)}/ws`;
	const ws = new WebSocket(url);
	ws.onmessage = (ev) => {
		let msg;
		try {
			msg = JSON.parse(ev.data);
		} catch {
			return;
		}
		if (msg.type === 'log') onLog?.(msg.line);
		else if (msg.type === 'done') onDone?.(msg);
		else if (msg.type === 'error') onError?.(msg);
	};
	ws.onerror = () => onError?.({ detail: 'WebSocket connection error' });
	return ws;
}
