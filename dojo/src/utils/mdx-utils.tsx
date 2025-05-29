import React from 'react';
import { MDXComponents } from '@/components/ui/mdx-components';
import { MDXProvider } from '@mdx-js/react';
import ReactMarkdown from 'react-markdown';

/**
 * Enhanced MDX content renderer component 
 */
export const MDXRenderer: React.FC<{
  content: string;
  demoId?: string;
}> = ({ content, demoId }) => {
  // Process content to enhance video tags
  const processedVideos = React.useMemo(() => {
    if (!content) return '';
    
    // Extract and process video tags
    const videoRegex = /<Video\s+src="([^"]+)"([^>]*)>/gi;
    let match;
    let processedHtml = '';
    
    while ((match = videoRegex.exec(content)) !== null) {
      const [fullMatch, src, attrs] = match;
      let videoHtml = '';
      
      // Process the video source based on demoId
      if (demoId && !src.startsWith('http') && !src.startsWith('/')) {
        videoHtml = `<div class="video-wrapper"><video controls width="100%" src="/api/demo-assets?demoId=${demoId}&fileName=${src}"${attrs}></video></div>`;
      } else {
        videoHtml = `<div class="video-wrapper"><video controls width="100%" src="${src}"${attrs}></video></div>`;
      }
      
      processedHtml += videoHtml;
    }
    
    return processedHtml;
  }, [content, demoId]);

  // Early return if no content
  if (!content) return null;

  return (
    <MDXProvider components={MDXComponents}>
      <div className="mdx-content">
        {/* Render the markdown content with proper formatting */}
        <ReactMarkdown components={MDXComponents}>
          {content}
        </ReactMarkdown>
        
        {/* Insert processed video elements if any */}
        {processedVideos && (
          <div 
            className="mt-4"
            dangerouslySetInnerHTML={{ __html: processedVideos }} 
          />
        )}
      </div>
    </MDXProvider>
  );
};

/**
 * Safe component rendering with error boundary
 */
export const SafeComponent: React.FC<{
  component: React.ComponentType | (() => React.ReactNode);
  fallback?: React.ReactNode;
}> = ({ 
  component: Component, 
  fallback = <div className="p-4 text-amber-600">Content could not be displayed</div> 
}) => {
  if (!Component) return <>{fallback}</>;
  
  try {
    return typeof Component === 'function' ? (
      typeof Component.prototype?.render === 'function' ? (
        <Component />
      ) : (
        <>{(Component as () => React.ReactNode)()}</>
      )
    ) : (
      <>{Component}</>
    );
  } catch (error) {
    console.error('Error rendering component:', error);
    return <>{fallback}</>;
  }
}; 