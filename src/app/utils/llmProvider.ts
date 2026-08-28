/**
 * Reads LLM provider settings from sessionStorage and returns
 * the headers + body fields needed for /api/audit, /api/store-summary, /api/qa.
 */

export type ProviderType = 'gemini' | 'deepseek' | 'openai_compatible';

export interface LLMSettings {
  provider: ProviderType;
  headers: Record<string, string>;
  /** Extra body fields to merge into POST JSON (provider, modelName). */
  body: Record<string, string>;
}

export function getLLMSettings(): LLMSettings {
  const provider = (sessionStorage.getItem('truerating_llm_provider') || 'gemini') as ProviderType;

  const headers: Record<string, string> = {};
  const body: Record<string, string> = { provider };

  if (provider === 'gemini') {
    const key = sessionStorage.getItem('truerating_gemini_api_key') || '';
    if (key) headers['X-Gemini-API-Key'] = key;
  } else if (provider === 'deepseek') {
    const key = sessionStorage.getItem('truerating_deepseek_api_key') || '';
    if (key) headers['X-DeepSeek-API-Key'] = key;
  } else if (provider === 'openai_compatible') {
    const key = sessionStorage.getItem('truerating_custom_api_key') || '';
    const baseUrl = sessionStorage.getItem('truerating_custom_base_url') || '';
    const model = sessionStorage.getItem('truerating_custom_model_name') || '';
    if (key) headers['X-Custom-API-Key'] = key;
    if (baseUrl) headers['X-Custom-Base-URL'] = baseUrl;
    if (model) body.modelName = model;
  }

  return { provider, headers, body };
}

/** Returns true if the user has a usable LLM key configured (for QA gating). */
export function hasLLMKey(): boolean {
  const provider = (sessionStorage.getItem('truerating_llm_provider') || 'gemini') as ProviderType;
  if (provider === 'gemini') {
    // Gemini works without a user key (server has default)
    return true;
  }
  if (provider === 'deepseek') {
    return !!sessionStorage.getItem('truerating_deepseek_api_key');
  }
  if (provider === 'openai_compatible') {
    return !!(
      sessionStorage.getItem('truerating_custom_api_key') &&
      sessionStorage.getItem('truerating_custom_base_url') &&
      sessionStorage.getItem('truerating_custom_model_name')
    );
  }
  return false;
}
