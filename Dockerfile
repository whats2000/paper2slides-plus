FROM python:3.10-slim

# Install system dependencies for LaTeX compilation and PDF processing
RUN apt-get update && apt-get install -y \
    texlive-latex-base \
    texlive-latex-recommended \
    texlive-latex-extra \
    texlive-fonts-recommended \
    texlive-fonts-extra \
    texlive-lang-all \
    texlive-science \
    latexmk \
    chktex \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Install uv for faster and safer Python package management
RUN pip install uv

# Set working directory to /app so Streamlit watches the project directory
WORKDIR /app

# Copy project files and install Python dependencies using uv
COPY pyproject.toml uv.lock ./
RUN uv sync

# Copy the rest of the application code into /app
COPY . /app

# Expose the port Streamlit runs on
EXPOSE 8501

# Run the Streamlit app using uv
CMD ["uv", "run", "streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
