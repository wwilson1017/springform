import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ReportTable } from './ReportTable';

describe('report table', () => {
  it('shows *_cents columns as money and leaves other numbers alone', () => {
    render(<ReportTable result={{ columns: ['customer', 'orders', 'revenue_cents'], rows: [['Ada', 12, 171720], ['Bo', 3, null]] }} />);
    expect(screen.getAllByRole('columnheader').map(h => h.textContent)).toEqual(['customer', 'orders', 'revenue']);
    expect(screen.getByText('1,717.20')).toBeTruthy();
    expect(screen.getByText('12')).toBeTruthy();
    expect(screen.queryByText('171720')).toBeNull();
  });
});
