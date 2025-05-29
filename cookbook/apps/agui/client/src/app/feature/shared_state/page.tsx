"use client";
import { CopilotKit, useCoAgent, useCopilotChat } from "@copilotkit/react-core";
import { CopilotSidebar } from "@copilotkit/react-ui";
import { useState, useEffect, useRef } from "react";
import { Role, TextMessage } from "@copilotkit/runtime-client-gql";
import "@copilotkit/react-ui/styles.css";
import "./style.css";

enum SkillLevel {
  BEGINNER = "Beginner",
  INTERMEDIATE = "Intermediate",
  ADVANCED = "Advanced",
}

enum SpecialPreferences {
  HighProtein = "High Protein",
  LowCarb = "Low Carb",
  Spicy = "Spicy",
  BudgetFriendly = "Budget-Friendly",
  OnePotMeal = "One-Pot Meal",
  Vegetarian = "Vegetarian",
  Vegan = "Vegan",
}

enum CookingTime {
  FiveMin = "5 min",
  FifteenMin = "15 min",
  ThirtyMin = "30 min",
  FortyFiveMin = "45 min",
  SixtyPlusMin = "60+ min",
}

const cookingTimeValues = [
  { label: CookingTime.FiveMin, value: 0 },
  { label: CookingTime.FifteenMin, value: 1 },
  { label: CookingTime.ThirtyMin, value: 2 },
  { label: CookingTime.FortyFiveMin, value: 3 },
  { label: CookingTime.SixtyPlusMin, value: 4 },
];

export default function SharedState() {
  return (
    <CopilotKit
      runtimeUrl="/api/copilotkit"
      showDevConsole={false}
      // agent lock to the relevant agent
      agent="sharedStateAgent"
    >
      <div
        className="min-h-screen w-full flex items-center justify-center"
        style={
          {
            backgroundImage: "url('/shared_state_background.png')",
            backgroundSize: "cover",
            backgroundPosition: "center",
            backgroundRepeat: "no-repeat",
          } as React.CSSProperties
        }
      >
        <Recipe />
        <CopilotSidebar
          defaultOpen={true}
          labels={{
            title: "AI Recipe Assistant",
            initial: "Hi 👋 How can I help with your recipe?",
          }}
          clickOutsideToClose={false}
        />
      </div>
    </CopilotKit>
  );
}

interface Recipe {
  skill_level: SkillLevel;
  special_preferences: SpecialPreferences[];
  cooking_time: CookingTime;
  ingredients: string;
  instructions: string;
}

interface RecipeAgentState {
  recipe: Recipe;
}

const INITIAL_STATE: RecipeAgentState = {
  recipe: {
    skill_level: SkillLevel.BEGINNER,
    special_preferences: [],
    cooking_time: CookingTime.FifteenMin,
    ingredients: "",
    instructions: "",
  },
};

function Recipe() {
  const { state: agentState, setState: setAgentState } =
    useCoAgent<RecipeAgentState>({
      name: "sharedStateAgent",
      initialState: INITIAL_STATE,
    });

  const [recipe, setRecipe] = useState(INITIAL_STATE.recipe);
  const { appendMessage, isLoading } = useCopilotChat();

  const updateRecipe = (partialRecipe: Partial<Recipe>) => {
    setAgentState({
      ...agentState,
      recipe: {
        ...recipe,
        ...partialRecipe,
      },
    });
    setRecipe({
      ...recipe,
      ...partialRecipe,
    });
  };

  const newRecipeState = { ...recipe };
  const newChangedKeys = [];
  const changedKeysRef = useRef<string[]>([]);

  for (const key in recipe) {
    if (
      (agentState.recipe as any)[key] !== undefined &&
      (agentState.recipe as any)[key] !== null
    ) {
      let agentValue = (agentState.recipe as any)[key];
      const recipeValue = (recipe as any)[key];

      if (Array.isArray(agentValue) && Array.isArray(recipeValue)) {
        agentValue.sort();
      }

      // Check if agentValue is a string and replace \n with actual newlines
      if (typeof agentValue === "string") {
        agentValue = agentValue.replace(/\\n/g, "\n");
      }

      if (JSON.stringify(agentValue) !== JSON.stringify(recipeValue)) {
        (newRecipeState as any)[key] = agentValue;
        newChangedKeys.push(key);
      }
    }
  }

  if (newChangedKeys.length > 0) {
    changedKeysRef.current = newChangedKeys;
  } else if (!isLoading) {
    changedKeysRef.current = [];
  }

  useEffect(() => {
    setRecipe(newRecipeState);
  }, [JSON.stringify(newRecipeState)]);

  const handleSkillLevelChange = (
    event: React.ChangeEvent<HTMLSelectElement>
  ) => {
    updateRecipe({
      skill_level: event.target.value as SkillLevel,
    });
  };

  const handlePreferenceChange = (
    preference: SpecialPreferences,
    checked: boolean
  ) => {
    if (checked) {
      updateRecipe({
        special_preferences: [
          ...agentState.recipe.special_preferences,
          preference,
        ],
      });
    } else {
      updateRecipe({
        special_preferences: agentState.recipe.special_preferences.filter(
          (p) => p !== preference
        ),
      });
    }
  };

  const handleCookingTimeChange = (
    event: React.ChangeEvent<HTMLInputElement>
  ) => {
    updateRecipe({
      cooking_time: cookingTimeValues[Number(event.target.value)].label,
    });
  };

  const handleIngredientsChange = (
    event: React.ChangeEvent<HTMLTextAreaElement>
  ) => {
    updateRecipe({
      ingredients: event.target.value,
    });
  };

  const handleInstructionsChange = (
    event: React.ChangeEvent<HTMLTextAreaElement>
  ) => {
    updateRecipe({
      instructions: event.target.value,
    });
  };

  return (
    <form
      className="w-full max-w-lg p-6 rounded shadow-md text-black"
      style={{
        backgroundColor: "rgba(255, 255, 255, 0.9)", // Semi-transparent white
        backdropFilter: "blur(10px)", // Apply blur for frosted effect
        WebkitBackdropFilter: "blur(10px)", // For Safari support
        boxShadow: "0 4px 30px rgba(0, 0, 0, 0.1)", // Subtle shadow for depth
      }}
    >
      <div className="mb-4 relative">
        {changedKeysRef.current.includes("skill_level") && <Ping />}
        <label
          className="block text-gray-700 text-sm font-bold mb-2"
          htmlFor="skillLevel"
        >
          Skill Level
        </label>
        <select
          className="shadow appearance-none border rounded w-full py-2 px-3 text-gray-700 leading-tight focus:outline-none focus:shadow-outline"
          id="skillLevel"
          value={recipe.skill_level}
          onChange={handleSkillLevelChange}
        >
          {Object.values(SkillLevel).map((level) => (
            <option key={level} value={level}>
              {level}
            </option>
          ))}
        </select>
      </div>
      <div className="mb-4 relative">
        {changedKeysRef.current.includes("cooking_time") && <Ping />}
        <label
          className="block text-gray-700 text-sm font-bold mb-2"
          htmlFor="cookingTime"
        >
          Cooking Time: {recipe.cooking_time}
        </label>
        <input
          type="range"
          id="cookingTime"
          min="0"
          max={cookingTimeValues.length - 1}
          value={cookingTimeValues.findIndex(
            (value) => value.label === recipe.cooking_time
          )}
          onChange={handleCookingTimeChange}
          className="w-full h-2 bg-gray-200 shadow rounded-lg appearance-none cursor-pointer focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>
      <div className="mb-4 relative">
        {changedKeysRef.current.includes("special_preferences") && <Ping />}
        <label className="block text-gray-700 text-sm font-bold mb-4">
          Special Preferences:
        </label>
        <div className="flex flex-wrap mt-2">
          {Object.values(SpecialPreferences).map((preference) => (
            <label
              key={preference}
              className="flex items-center mr-4 mb-2 whitespace-nowrap uppercase"
              style={{ fontSize: "10px", fontWeight: "bold" }}
            >
              <input
                type="checkbox"
                checked={recipe.special_preferences.includes(preference)}
                onChange={(e) =>
                  handlePreferenceChange(preference, e.target.checked)
                }
                className="mr-1"
              />
              {preference}
            </label>
          ))}
        </div>
      </div>

      <div className="mb-4 relative">
        {changedKeysRef.current.includes("ingredients") && <Ping />}
        <label
          className="block text-gray-700 text-sm font-bold mb-2"
          htmlFor="ingredients"
        >
          Ingredients:
        </label>
        <textarea
          id="ingredients"
          value={recipe.ingredients}
          onChange={handleIngredientsChange}
          className="shadow appearance-none border rounded w-full py-2 px-3 text-gray-700 leading-tight focus:outline-none focus:shadow-outline"
          rows={4}
          placeholder="Enter ingredients here..."
        />
      </div>

      <div className="mb-4 relative">
        {changedKeysRef.current.includes("instructions") && <Ping />}
        <label
          className="block text-gray-700 text-sm font-bold mb-2"
          htmlFor="instructions"
        >
          Instructions:
        </label>
        <textarea
          id="instructions"
          value={recipe.instructions}
          onChange={handleInstructionsChange}
          className="shadow appearance-none border rounded w-full py-2 px-3 text-gray-700 leading-tight focus:outline-none focus:shadow-outline"
          rows={6}
          placeholder="Enter instructions here..."
        />
      </div>

      <div className="flex items-center justify-end mt-2">
        <button
          className={`${
            isLoading
              ? "bg-gray-400 cursor-not-allowed"
              : "bg-black hover:bg-gray-800"
          } text-white font-base py-2 px-4 rounded focus:outline-none focus:shadow-outline`}
          type="button"
          onClick={() => {
            if (!isLoading) {
              appendMessage(
                new TextMessage({
                  content: "Improve the recipe",
                  role: Role.User,
                })
              );
            }
          }}
          disabled={isLoading}
        >
          {isLoading ? "Please Wait..." : "Improve with AI"}
        </button>
      </div>
    </form>
  );
}

function Ping() {
  return (
    <span className="absolute flex size-3 top-0 right-0">
      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-sky-400 opacity-75"></span>
      <span className="relative inline-flex size-3 rounded-full bg-sky-500"></span>
    </span>
  );
}
