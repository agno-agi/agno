import React from 'react';
import { DemoConfig } from '@/types/demo';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';

interface DemoListProps {
  demos: DemoConfig[];
  selectedDemo?: string;
  onSelect: (demoId: string) => void;
  llmSelector?: React.ReactNode;
}

export function DemoList({ demos, selectedDemo, onSelect, llmSelector }: DemoListProps) {
  return (
    <div className="h-full">
      <div className="px-4 pt-3 pb-2">
        <h2 className="text-xs uppercase tracking-wider font-semibold text-muted-foreground mb-1">Demos</h2>
        {llmSelector && <div className="mt-2">{llmSelector}</div>}
      </div>
      <ul className="px-2 space-y-0.5">
        {demos.map((demo) => (
          <li key={demo.id}>
            <button
              className={cn(
                'w-full text-left py-2 px-3 rounded-md hover:bg-accent/50 transition-colors',
                'flex flex-col gap-0.5',
                selectedDemo === demo.id && 'bg-accent'
              )}
              onClick={() => onSelect(demo.id)}
            >
              <div className="text-sm font-medium leading-tight">{demo.name}</div>
              <div className="text-xs text-muted-foreground line-clamp-2 leading-relaxed">
                {demo.description}
              </div>
              {demo.tags && demo.tags.length > 0 && (
                <div className="flex gap-1 flex-wrap mt-0.5">
                  {demo.tags.map((tag) => (
                    <Badge 
                      key={tag} 
                      variant={selectedDemo === demo.id ? "default" : "secondary"} 
                      className={cn(
                        "text-xs px-1.5 py-0.5 rounded-full",
                        selectedDemo === demo.id && "bg-primary text-primary-foreground border-transparent"
                      )}
                    >
                      {tag}
                    </Badge>
                  ))}
                </div>
              )}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
} 