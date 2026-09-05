import BrandLogo from '@/components/BrandLogo';

const BrandSplash = () => (
  <div className="brand-splash fixed inset-0 z-[100] flex flex-col items-center justify-center gap-4 bg-background">
    <div className="brand-logo-in">
      <BrandLogo className="size-20 rounded-2xl shadow-lg" />
    </div>
    <div className="brand-logo-in brand-logo-in-delay flex flex-col items-center gap-1">
      <p className="text-xl font-semibold tracking-wide text-foreground">繁工AI</p>
      <p className="text-sm text-muted-foreground">复杂工程，AI 化简</p>
    </div>
  </div>
);

export default BrandSplash;
