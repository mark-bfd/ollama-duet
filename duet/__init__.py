"""ollama-duet — one assistant, two brains, one API shape.

A local Ollama model answers the everyday questions for free; a big
open-weight model on Ollama's cloud catches the hard ones and covers
downtime, under the flat-fee subscription. Same native /api/chat call,
same tools, same loop — only model/url/key differ.
"""
from duet.router import Duet, Turn, BrainUnreachable, LOCAL_URL, DIRECT_URL
from duet.tools import Tool, Toolbox

__all__ = ["Duet", "Turn", "BrainUnreachable", "Tool", "Toolbox",
           "LOCAL_URL", "DIRECT_URL"]
__version__ = "1.0.0"
