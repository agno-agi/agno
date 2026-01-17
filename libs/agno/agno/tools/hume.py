"""Hume AI Toolkit for Agno SDK

Comprehensive toolkit for emotional AI using Hume's Expression Measurement, EVI, and TTS APIs.
Analyzes 48-53 emotions from text, audio, and video for building empathic AI applications.

Requirements:
- pip install hume
- Set HUME_API_KEY environment variable

Get your API key from: https://platform.hume.ai/
"""

import json
import asyncio
from os import getenv
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug

try:
    from hume import HumeClient
    from hume.models.config import LanguageConfig
except ImportError:
    raise ImportError("Install hume SDK: pip install hume")


class HumeTools(Toolkit):
    """Hume AI toolkit for emotional expression analysis and empathic AI.
    
    Args:
        api_key: Hume AI API key. Can also be set via HUME_API_KEY environment variable.
    """

    def __init__(self, api_key: Optional[str] = None, **kwargs):
        self.api_key = api_key or getenv("HUME_API_KEY")
        if not self.api_key:
            raise ValueError("HUME_API_KEY required. Get key from https://platform.hume.ai/")
        
        self.client = HumeClient(api_key=self.api_key)
        
        tools: List[Any] = [
            self.analyze_text_emotion,
            self.analyze_batch_emotions,
            self.list_evi_configs,
            self.synthesize_speech,
        ]
        
        super().__init__(name="hume", tools=tools, **kwargs)

    def analyze_text_emotion(self, text: str, top_n: int = 10) -> str:
        """Analyze emotions in text using Hume's language model.
        
        Args:
            text: Text to analyze for emotional content.
            top_n: Number of top emotions to return (default: 10).
            
        Returns:
            JSON string with emotion predictions and scores.
        """
        log_debug(f"Analyzing text emotion: {text[:50]}...")
        
        try:
            from hume.expression_measurement.stream import StreamConnectOptions
            
            async def analyze():
                config = LanguageConfig()
                options = StreamConnectOptions(config=config)
                
                async with self.client.expression_measurement.stream.connect(options=options) as socket:
                    result = await socket.send_text(text)
                    
                    if hasattr(result, 'language') and result.language:
                        predictions = []
                        for pred in result.language.predictions:
                            top_emotions = sorted(pred.emotions, key=lambda x: x.score, reverse=True)[:top_n]
                            predictions.append({
                                "text": pred.text,
                                "emotions": [{"name": e.name, "score": round(e.score, 4)} for e in top_emotions]
                            })
                        return {"success": True, "predictions": predictions}
                    
                    return {"error": "No predictions returned", "success": False}
            
            result = asyncio.run(analyze())
            return json.dumps(result, indent=2)
            
        except Exception as e:
            return json.dumps({"error": str(e), "success": False}, indent=2)

    def analyze_batch_emotions(self, texts: List[str]) -> str:
        """Analyze emotions in multiple text samples.
        
        Args:
            texts: List of text samples to analyze.
            
        Returns:
            JSON string with batch emotion predictions.
        """
        log_debug(f"Batch analyzing {len(texts)} texts")
        
        try:
            from hume.expression_measurement.stream import StreamConnectOptions
            
            async def analyze_batch():
                config = LanguageConfig()
                options = StreamConnectOptions(config=config)
                all_predictions = []
                
                async with self.client.expression_measurement.stream.connect(options=options) as socket:
                    for idx, text in enumerate(texts):
                        result = await socket.send_text(text)
                        if hasattr(result, 'language') and result.language:
                            for pred in result.language.predictions:
                                top_5 = sorted(pred.emotions, key=lambda x: x.score, reverse=True)[:5]
                                all_predictions.append({
                                    "index": idx,
                                    "text": pred.text,
                                    "top_emotions": [{"name": e.name, "score": round(e.score, 4)} for e in top_5]
                                })
                
                return {"success": True, "count": len(all_predictions), "predictions": all_predictions}
            
            result = asyncio.run(analyze_batch())
            return json.dumps(result, indent=2)
            
        except Exception as e:
            return json.dumps({"error": str(e), "success": False}, indent=2)

    def list_evi_configs(self) -> str:
        """List all Empathic Voice Interface (EVI) configurations.
        
        Returns:
            JSON string with list of EVI configs.
        """
        log_debug("Fetching EVI configs")
        
        try:
            configs = self.client.empathic_voice.configs.list_configs()
            config_list = []
            for config in configs:
                config_list.append({
                    "id": getattr(config, 'id', None),
                    "name": getattr(config, 'name', None),
                    "version": getattr(config, 'version', None),
                })
            return json.dumps({"success": True, "count": len(config_list), "configs": config_list}, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e), "success": False}, indent=2)

    def synthesize_speech(self, text: str, voice: Optional[str] = None) -> str:
        """Synthesize speech from text using Hume TTS.
        
        Args:
            text: Text to convert to speech.
            voice: Optional voice ID for synthesis.
            
        Returns:
            JSON string with synthesis status.
        """
        log_debug(f"Synthesizing speech: {text[:50]}...")
        
        try:
            if voice:
                response = self.client.tts.synthesize(text=text, voice=voice)
            else:
                response = self.client.tts.synthesize(text=text)
            
            return json.dumps({
                "success": True,
                "text": text,
                "voice": voice,
                "note": "Audio generated. Use SDK directly to access audio bytes."
            }, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e), "success": False}, indent=2)
