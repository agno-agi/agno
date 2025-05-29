import React from 'react';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Button } from '@/components/ui/button';
import { LLMProvider } from '@/types/demo';
import { Brain } from 'lucide-react';

interface LLMSelectorProps {
  value: LLMProvider;
  onChange: (provider: LLMProvider) => void;
}

const providers: { value: LLMProvider; label: string }[] = [
  { value: 'openai', label: 'OpenAI' },
  { value: 'anthropic', label: 'Anthropic' },
];

export function LLMSelector({ value, onChange }: LLMSelectorProps) {
  const selectedProvider = providers.find((p) => p.value === value);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" className="w-full justify-start gap-2">
          <Brain className="h-4 w-4" />
          {selectedProvider?.label || 'Select Provider'}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-[180px]">
        {providers.map((provider) => (
          <DropdownMenuItem
            key={provider.value}
            onClick={() => onChange(provider.value)}
          >
            {provider.label}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
} 