import { describe, expect, it } from 'vitest';
import { createSseParser, readEvents } from './sse';

const frame = (event: object) => `data: ${JSON.stringify(event)}\n\n`;

describe('createSseParser', () => {
  it('returns each complete event and holds a partial one until it ends', () => {
    const p = createSseParser();
    const text = frame({ type: 'text', text: 'Hel' }) + frame({ type: 'text', text: 'lo' });
    const cut = text.length - 7;
    expect(p.push(text.slice(0, cut))).toEqual([{ type: 'text', text: 'Hel' }]);
    expect(p.push(text.slice(cut))).toEqual([{ type: 'text', text: 'lo' }]);
  });

  it('reassembles an event split anywhere, CRLF pairs included', () => {
    const text = 'data: {"type":"done","model":"m"}\r\n\r\n';
    for (let i = 1; i < text.length; i++) {
      const p = createSseParser();
      const events = [...p.push(text.slice(0, i)), ...p.push(text.slice(i)), ...p.end()];
      expect(events, `split at ${i}`).toEqual([{ type: 'done', model: 'm' }]);
    }
  });

  it('skips malformed frames, comments and other fields without stopping', () => {
    const p = createSseParser();
    const events = p.push(': keep-alive\n\ndata: {not json\n\nevent: x\ndata: {"no":"type"}\n\nid: 7\ndata: {"type":"compacted"}\n\n');
    expect(events).toEqual([{ type: 'compacted' }]);
  });

  it('joins multi-line data and accepts "data:" without a space', () => {
    const p = createSseParser();
    expect(p.push('data:{"type":"text",\ndata: "text":"x"}\n\n')).toEqual([{ type: 'text', text: 'x' }]);
  });

  it('keeps a final event that arrives without its blank line', () => {
    const p = createSseParser();
    expect(p.push('data: {"type":"done","model":"m"}')).toEqual([]);
    expect(p.end()).toEqual([{ type: 'done', model: 'm' }]);
  });
});

describe('readEvents', () => {
  it('reads a byte stream to its end, multi-byte characters split across chunks included', async () => {
    const bytes = new TextEncoder().encode(frame({ type: 'text', text: 'café ✓' }) + frame({ type: 'done', model: 'm' }));
    const split = bytes.indexOf(0xc3) + 1; // inside the two-byte "é"
    const body = new ReadableStream<Uint8Array>({
      start(c) { c.enqueue(bytes.slice(0, split)); c.enqueue(bytes.slice(split)); c.close(); },
    });
    const seen: unknown[] = [];
    await readEvents(body, events => seen.push(...events));
    expect(seen).toEqual([{ type: 'text', text: 'café ✓' }, { type: 'done', model: 'm' }]);
  });

  it('rejects when the connection drops, after handing over what arrived', async () => {
    let controller!: ReadableStreamDefaultController<Uint8Array>;
    const body = new ReadableStream<Uint8Array>({ start(c) { controller = c; } });
    const seen: unknown[] = [];
    const reading = readEvents(body, events => seen.push(...events));
    controller.enqueue(new TextEncoder().encode(frame({ type: 'text', text: 'partial' })));
    await Promise.resolve();
    controller.error(new TypeError('network error'));
    await expect(reading).rejects.toThrow('network error');
    expect(seen).toEqual([{ type: 'text', text: 'partial' }]);
  });
});
