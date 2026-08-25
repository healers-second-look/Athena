import { useNavigate } from 'react-router-dom'

export default function ChatLanding() {
  const navigate = useNavigate()

  return (
    <div className="landing">
      {/* Header */}
      <header className="landing-header">
        <div className="landing-header-inner">
          <div className="brand">
            <span className="material-symbols-outlined brand-icon"
                  style={{ fontVariationSettings: "'FILL' 0" }}>
              neurology
            </span>
            <span className="brand-name">Athena</span>
          </div>
          <nav className="landing-nav">
            <a href="#" className="active">Synthesis</a>
            <a href="#">Evidence</a>
            <a href="#">Knowledge Graph</a>
          </nav>
        </div>
      </header>

      {/* Hero */}
      <section className="hero">
        <h1>Clinical Evidence, Synthesized</h1>
        <p>
          AI-powered research assistant grounded in real clinical evidence
          from CIViC, PubMed, and your knowledge graph.
        </p>
        <button className="btn-primary" onClick={() => navigate('/chat/new')}>
          <span className="material-symbols-outlined" style={{ fontSize: 18 }}>
            add
          </span>
          Start a New Chat
        </button>
      </section>

      {/* Features */}
      <section className="features">
        <div className="feature-card periwinkle">
          <span className="material-symbols-outlined feature-icon">
            model_training
          </span>
          <h3>Multi-Model Support</h3>
          <p>
            Seamlessly switch between leading LLMs to find the best
            reasoning engine for your specific clinical query.
          </p>
        </div>
        <div className="feature-card apricot">
          <span className="material-symbols-outlined feature-icon">
            account_tree
          </span>
          <h3>Knowledge Graph Context</h3>
          <p>
            Grounds responses in a deeply structured ontology, ensuring
            relationships between entities are logically sound.
          </p>
        </div>
        <div className="feature-card sage">
          <span className="material-symbols-outlined feature-icon">
            verified
          </span>
          <h3>Evidence Grading</h3>
          <p>
            Automatically categorizes citations by tier, providing transparent
            confidence levels for therapeutic recommendations.
          </p>
        </div>
      </section>

      {/* Footer */}
      <footer className="landing-footer">
        <div className="landing-footer-inner">
          <div>
            <span className="brand-name" style={{ fontSize: 16 }}>Athena</span>
            <p>Built for clinicians and researchers.</p>
          </div>
        </div>
      </footer>
    </div>
  )
}
