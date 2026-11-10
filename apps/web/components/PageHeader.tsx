export function PageHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3 mb-6">
      <div>
        <h1 className="text-xl lg:text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="text-sm text-muted mt-1 max-w-xl">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}
