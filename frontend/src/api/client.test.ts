import { describe, expect, it } from 'vitest';
import { createSseParser } from './client';
describe('SSE transport', () => {
  it('reassembles arbitrary chunk boundaries and ignores heartbeat comments', () => {
    const events: string[] = [];
    const parser = createSseParser((value) => events.push(value));
    parser.push(': keepalive\r\n\r\nda');
    parser.push('ta: {"type":"message"}\r\n\r');
    parser.push('\ndata: first\ndata: second\n\ndata: [DONE]\n\n');
    expect(events).toEqual(['{"type":"message"}', 'first\nsecond', '[DONE]']);
  });
  it('flushes a server final event even without a double newline', () => {
    const events: string[] = [];
    const parser = createSseParser((value) => events.push(value));
    parser.push('data: final');
    parser.finish();
    expect(events).toEqual(['final']);
  });
});
