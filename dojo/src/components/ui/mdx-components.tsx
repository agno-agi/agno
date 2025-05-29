import React from 'react';
import { cn } from '@/lib/utils';
import { MarkdownComponents } from './markdown-components';
import { MDXProvider } from '@mdx-js/react';
import type { Components } from 'react-markdown';

// Video component specifically for MDX
export const VideoPlayer = ({ 
  src, 
  width = "100%", 
  className, 
  ...props 
}: React.VideoHTMLAttributes<HTMLVideoElement> & { src: string }) => {
  return (
    <div className="my-8">
      <video 
        controls 
        width={width} 
        className={cn("rounded-lg w-full", className)} 
        {...props}
      >
        <source src={src} type="video/mp4" />
        Your browser does not support the video tag.
      </video>
    </div>
  );
};

// Type definition for MDX components that includes our custom components
type CustomMDXComponents = Components & {
  Video: typeof VideoPlayer;
  video: typeof VideoPlayer;
};

// Combine all components for MDX
export const MDXComponents: CustomMDXComponents = {
  ...MarkdownComponents,
  // Custom components for MDX
  Video: VideoPlayer,
  video: VideoPlayer,
} as CustomMDXComponents;

// MDX Provider wrapper component
export const MDXContent: React.FC<{children: React.ReactNode}> = ({ children }) => {
  return (
    <MDXProvider components={MDXComponents}>
      <div className="mdx-content">
        {children}
      </div>
    </MDXProvider>
  );
}; 