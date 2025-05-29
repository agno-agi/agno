"use client";

import React, { useState, useEffect } from "react";
import Image from "next/image";
import { useRouter, usePathname } from "next/navigation";
import { DemoList } from "@/components/demo-list/demo-list";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Eye, Code, Book } from "lucide-react";
import config from "@/config";

interface SidebarProps {
  activeTab?: string;
  onTabChange?: (tab: string) => void;
  readmeContent?: string | null;
}

export function Sidebar({ activeTab = "preview", onTabChange, readmeContent }: SidebarProps) {
  const router = useRouter();
  const pathname = usePathname();
  const [isDarkTheme, setIsDarkTheme] = useState<boolean>(false);
  
  // Extract the current demo ID from the pathname
  const pathParts = pathname.split('/');
  const currentDemoId = pathParts[pathParts.length - 1];
  
  // Handle selecting a demo
  const handleDemoSelect = (demoId: string) => {
    const demo = config.find((d) => d.id === demoId);
    if (demo) {
      router.push(demo.path);
    }
  };

  // Check for dark mode using media query
  useEffect(() => {
    // Check if we're in the browser
    if (typeof window !== "undefined") {
      // Initial check
      setIsDarkTheme(window.matchMedia("(prefers-color-scheme: dark)").matches);

      // Listen for changes
      const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
      const handleChange = (e: MediaQueryListEvent) => {
        setIsDarkTheme(e.matches);
      };

      mediaQuery.addEventListener("change", handleChange);

      // Also check for .dark class which is added by next-themes
      const observer = new MutationObserver(() => {
        setIsDarkTheme(document.documentElement.classList.contains("dark"));
      });

      observer.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ["class"],
      });

      return () => {
        mediaQuery.removeEventListener("change", handleChange);
        observer.disconnect();
      };
    }
  }, []);

  const handleTabChange = (value: string) => {
    if (onTabChange) {
      onTabChange(value);
    }
  };

  return (
    <div className="flex flex-col h-full w-74 min-w-[296px] flex-shrink-0 border-r">
      {/* Sidebar Header */}
      <div className="p-4 border-b bg-background">
        <div className="flex items-center justify-between ml-1">
          <div className="flex items-start flex-col">
            <Image
              src={isDarkTheme ? "/logo_light.webp" : "/logo_dark.webp"}
              width={120}
              height={24}
              alt="CopilotKit"
              className="h-6 w-auto object-contain"
            />
            <h1
              className={`text-lg font-extralight ${
                isDarkTheme ? "text-white" : "text-gray-900"
              }`}
            >
              Interactive Demos
            </h1>
          </div>

          <ThemeToggle />
        </div>
      </div>

      {/* Controls Section */}
      <div className="p-4 border-b bg-background">
        {/* Preview/Code Tabs */}
        <div className="mb-1">
          <label className="block text-sm font-medium text-muted-foreground mb-2">
            View
          </label>
          <Tabs
            value={activeTab}
            onValueChange={handleTabChange}
            className="w-full"
          >
            <TabsList className="w-full h-9 bg-background border shadow-sm rounded-lg p-1">
              <TabsTrigger
                value="preview"
                className="flex-1 h-7 px-2 text-sm font-medium gap-1 rounded-md data-[state=active]:bg-primary data-[state=active]:text-primary-foreground data-[state=active]:shadow"
              >
                <Eye className="h-3 w-3" />
                <span>Preview</span>
              </TabsTrigger>
              <TabsTrigger
                value="code"
                className="flex-1 h-7 px-2 text-sm font-medium gap-1 rounded-md data-[state=active]:bg-primary data-[state=active]:text-primary-foreground data-[state=active]:shadow"
              >
                <Code className="h-3 w-3" />
                <span>Code</span>
              </TabsTrigger>
              <TabsTrigger
                value="readme"
                className="flex-1 h-7 px-2 text-sm font-medium gap-1 rounded-md data-[state=active]:bg-primary data-[state=active]:text-primary-foreground data-[state=active]:shadow"
              >
                <Book className="h-3 w-3" />
                <span>Docs</span>
              </TabsTrigger>
            </TabsList>
          </Tabs>
        </div>
      </div>

      {/* Demo List */}
      <div className="flex-1 overflow-auto">
        <DemoList
          demos={config}
          selectedDemo={currentDemoId}
          onSelect={handleDemoSelect}
        />
      </div>
    </div>
  );
} 