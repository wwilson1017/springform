// The four icons the bar uses, inline so the app needs no icon dependency.
// Same 24-unit stroke geometry and names as the lucide-react icons they replace.
import type { ReactNode, SVGProps } from 'react';

function Icon({ children, ...props }: SVGProps<SVGSVGElement> & { children: ReactNode }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      {children}
    </svg>
  );
}

type Props = SVGProps<SVGSVGElement>;

export const Search = (p: Props) => (
  <Icon {...p}><circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" /></Icon>
);

export const X = (p: Props) => (
  <Icon {...p}><path d="M18 6 6 18" /><path d="m6 6 12 12" /></Icon>
);

export const ChevronDown = (p: Props) => (
  <Icon {...p}><path d="m6 9 6 6 6-6" /></Icon>
);

export const SlidersHorizontal = (p: Props) => (
  <Icon {...p}>
    <path d="M21 4h-7" /><path d="M10 4H3" /><path d="M21 12h-9" /><path d="M8 12H3" />
    <path d="M21 20h-5" /><path d="M12 20H3" />
    <path d="M14 2v4" /><path d="M8 10v4" /><path d="M16 18v4" />
  </Icon>
);
