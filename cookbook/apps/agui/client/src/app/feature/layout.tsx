export default function FeatureLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-(--copilot-kit-background-color) w-full h-full">
      {children}
    </div>
  );
}