/**
 * Server-sent events over a POST response. EventSource only does GET, so the chat reads
 * `fetch(...).body` and frames it here: events end at a blank line, `data:` lines inside one
 * event join with "\n", other fields and comments are ignored, and a frame that is not JSON is
 * skipped rather than ending the stream.
 */

import type { ChatEvent } from './types';

export interface SseParser {
  /** Feed decoded text; returns the events completed by it. */
  push(text: string): ChatEvent[];
  /** End of stream: a final event without its trailing blank line still counts. */
  end(): ChatEvent[];
}

export function createSseParser(): SseParser {
  let buffer = '';

  function frame(block: string): ChatEvent | null {
    const data = block.split('\n')
      .filter(line => line.startsWith('data:'))
      .map(line => line.slice(line.startsWith('data: ') ? 6 : 5))
      .join('\n');
    if (!data.trim()) return null;
    try {
      const event = JSON.parse(data);
      return event && typeof event.type === 'string' ? (event as ChatEvent) : null;
    } catch {
      return null;
    }
  }

  function drain(final: boolean): ChatEvent[] {
    // Only CRLF pairs: a lone CR may be the first half of one split across two chunks.
    buffer = buffer.replace(/\r\n/g, '\n');
    const blocks = buffer.split('\n\n');
    buffer = final ? '' : blocks.pop() ?? '';
    return blocks.map(frame).filter((e): e is ChatEvent => e !== null);
  }

  return {
    push(text) {
      buffer += text;
      return drain(false);
    },
    end() {
      return drain(true);
    },
  };
}

/**
 * Read a streaming response to its end, handing each batch of events to `onEvents`. Resolves
 * when the body ends; rejects when the connection drops (or the caller aborts the fetch).
 */
export async function readEvents(body: ReadableStream<Uint8Array>, onEvents: (events: ChatEvent[]) => void): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const parser = createSseParser();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      const events = parser.push(decoder.decode(value, { stream: true }));
      if (events.length) onEvents(events);
    }
    const rest = parser.push(decoder.decode());
    const last = [...rest, ...parser.end()];
    if (last.length) onEvents(last);
  } finally {
    reader.releaseLock();
  }
}
