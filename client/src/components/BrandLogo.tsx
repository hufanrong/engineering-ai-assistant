interface BrandLogoProps {
  className?: string;
}

const BrandLogo = ({ className }: BrandLogoProps) => (
  <svg
    viewBox="0 0 48 48"
    className={className}
    role="img"
    aria-label="繁工AI"
    xmlns="http://www.w3.org/2000/svg"
  >
    <rect width="48" height="48" rx="10" fill="#1E5AA8" />
    <g
      fill="none"
      stroke="#FFFFFF"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="33" cy="14" r="4.5" />
      <path d="M33 6v3M33 19v3M25 14h3M38 14h3M29.8 10.8l-2.5-2.5M36.2 10.8l2.5-2.5M29.8 17.2l-2.5 2.5M36.2 17.2l2.5 2.5" />
    </g>
    <polyline
      points="8,38 16,38 21,26 28,36 38,24"
      fill="none"
      stroke="#FFFFFF"
      strokeWidth="3"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <circle cx="8" cy="38" r="3" fill="#FFFFFF" />
    <circle cx="38" cy="24" r="3.4" fill="#FF7A00" />
  </svg>
);

export default BrandLogo;
