import React from 'react';
import { ViewerConfig } from '@/types/demo';
import { cn } from '@/lib/utils';

interface ViewerLayoutProps extends ViewerConfig {
  className?: string;
  children?: React.ReactNode;
  codeEditor?: React.ReactNode;
  fileTree?: React.ReactNode;
  sidebarHeader?: React.ReactNode;
}

export function ViewerLayout({
  className,
  children,
  codeEditor,
  fileTree,
  sidebarHeader,
  showCodeEditor = true,
  showFileTree = true,
}: ViewerLayoutProps) {
  return (
    <div className={cn('flex h-screen', className)}>
      <div className="flex flex-1 overflow-hidden">
        {showFileTree && (
          <aside className="w-64 border-r bg-muted/20 flex flex-col">
            {sidebarHeader}
            {fileTree}
          </aside>
        )}
        
        <main className="flex-1 overflow-auto">
          <div className="h-full">{children}</div>
        </main>

        {showCodeEditor && (
          <aside className="w-1/3 border-l bg-muted/20">
            {codeEditor}
          </aside>
        )}
      </div>
    </div>
  );
} 