TODO:
###


For the current logic in "powerpoint_template_workflow.py" what I can see if I request for typically 10 slides or more presentation file from Claude. It doesn't work. But if I try something like 3, 5, 7 slides presentation files, then it works most of the time. So, I have some thoughts of how to handle this situation so that it will always work,

1. Once user enters his query or prompt with "-p" command, we will first do query optimization and enhancment. Consider tonality, branding, styling, data context etc. properly. Don't overthink or be too creative.
2. Decide how many slides to be generated for the presentation file. This number can be either mentioned in side the user prompt or need to be decided by the llm targeing a optimum no. of slides
3. Next create a storyboard spread across separate markdown file mapped to each slide to be created. There should be a contnutation of the markdown contents for each file in a way that overall tonality, branding, styling, data context etc. should not be lost. Or we may think about a global, common markdown file to avoid any repeatations. Take your best judgment and approach.
4. Use a configurable/command line argument based chunk size (default 3) to decide how many times we will call Claude API to give us the PPTX files. Add max 2 retries for each claude call. I think Agno may have some inbuilt support, but anyway you can check and decide the best approach. Also, put a exponential delay between each normal chunk based calls with base value of 1000ms
5. Once all the files get created (if any internal claude api failure happens even after 2 retries, just log or print, but continue the flow), go for running the remaining steps like template based generation steps, image planning & generation etc. except the last visual step inspection. Generate the transformed files (template, image etc.) for each chunk run.
6. Now, based on the command line argument passed do visual inspection for each file's slides generated based on chunk based loop. If any changes needed, apply that change to the PPTX file, otherwise skip for next pptx file. While applying the required change, if you think relevant function logic is missing in python, then just log it in console irrespective of verbose mode with a suggestion that logic to be added. If you make any change to a particular slide, you also need to verify if that change is proper or any further change is needed. For any change do this inspection max 3 times.
7. Finally merge all the PPTX files to the final output pptx file

Note - If template file argument not passed, step 5 and 6 can be skipped. Only step 7 will be executed at the end.