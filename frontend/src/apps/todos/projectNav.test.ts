import { describe, expect, it } from 'vitest';
import { projectNeighbours } from './projectNav';

const P = (id: number, status: 'active' | 'completed' = 'active') => ({ id, status });

describe('projectNeighbours', () => {
  const list = [P(5), P(2, 'completed'), P(9), P(1), P(7, 'completed')];

  it('follows list order within the same status', () => {
    expect(projectNeighbours(list, 9)).toEqual({ prev: 5, next: 1 });
    expect(projectNeighbours(list, 2)).toEqual({ prev: 7, next: 7 });
  });

  it('wraps around at both ends', () => {
    expect(projectNeighbours(list, 5)).toEqual({ prev: 1, next: 9 });
    expect(projectNeighbours(list, 1)).toEqual({ prev: 9, next: 5 });
  });

  it('has no neighbours for a single or unknown project', () => {
    expect(projectNeighbours([P(3), P(4, 'completed')], 3)).toBeNull();
    expect(projectNeighbours(list, 42)).toBeNull();
    expect(projectNeighbours([], 1)).toBeNull();
  });
});
