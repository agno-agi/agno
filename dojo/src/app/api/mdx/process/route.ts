import { NextRequest, NextResponse } from 'next/server';
import filesJson from '../../../../files.json'
import { compile } from '@mdx-js/mdx';
import { FileEntry } from "@/components/file-tree/file-tree";

export async function POST(req: NextRequest) {
  try {
    const { demoId } = await req.json();

    // @ts-expect-error -- can index.
    const files: FileEntry[] = filesJson[demoId].files;
    const readmeFile = files.find(file => file.name.includes('.mdx') || file.name.includes('.md'));
    if (!readmeFile) {
      throw new Error('No readme file found.');
    }

    // Read the file content
    const content = readmeFile.content;

    // For MDX files, process them with MDX compiler
    if (readmeFile.name.endsWith('.mdx')) {
      try {
        // Compile the MDX to JSX
        const result = await compile(content, {
          outputFormat: 'function-body',
          development: process.env.NODE_ENV !== 'production',
        });
        
        return NextResponse.json({ content, compiled: String(result) });
      } catch (error) {
        console.error('Error compiling MDX:', error);
        return NextResponse.json(
          { error: 'Failed to compile MDX', details: String(error) },
          { status: 500 }
        );
      }
    }
    
    // For regular Markdown files, just return the content
    return NextResponse.json({ content });
  } catch (error) {
    console.error('Error processing file:', error);
    return NextResponse.json(
      { error: 'Internal server error', details: String(error) },
      { status: 500 }
    );
  }
} 