export interface RedactionRule {
  ruleId: string;
  pattern: RegExp;
  placeholder: string;
}

export function createRedactionRule(ruleId: string, pattern: RegExp): RedactionRule {
  return {
    ruleId,
    pattern,
    placeholder: `[REDACTED:${ruleId}]`,
  };
}

export const DEFAULT_RULES: RedactionRule[] = [
  createRedactionRule("bearer_token", /Bearer\s+[A-Za-z0-9\-\._~\+\/]+=*/gi),
  createRedactionRule(
    "private_key",
    /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/gi
  ),
  createRedactionRule("stripe_live_key", /sk_live_[0-9a-zA-Z]{24,}/g),
  createRedactionRule("stripe_test_key", /sk_test_[0-9a-zA-Z]{24,}/g),
  createRedactionRule("aws_key", /AKIA[0-9A-Z]{16}/g),
  createRedactionRule(
    "jwt_token",
    /eyJ[A-Za-z0-9-_=]+\.eyJ[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]*/g
  ),
];

export class Redactor {
  private rules: RedactionRule[];

  constructor(rules: RedactionRule[] = DEFAULT_RULES) {
    this.rules = rules;
  }

  public redactText(text: string): string {
    if (!text) return text;
    let result = text;
    for (const rule of this.rules) {
      result = result.replace(rule.pattern, rule.placeholder);
    }
    return result;
  }

  public redact(data: any, seen = new WeakSet()): any {
    if (typeof data === "string") {
      return this.redactText(data);
    }
    if (data === null || data === undefined) {
      return data;
    }
    if (typeof data === "object") {
      if (seen.has(data)) {
        return "[CIRCULAR]";
      }
      seen.add(data);
      if (Array.isArray(data)) {
        return data.map((item) => this.redact(item, seen));
      }
      const result: Record<string, any> = {};
      for (const [key, value] of Object.entries(data)) {
        const redactedKey = typeof key === "string" ? this.redactText(key) : key;
        result[redactedKey] = this.redact(value, seen);
      }
      return result;
    }
    return data;
  }
}

const defaultRedactor = new Redactor();

export function redactPayload(data: any): any {
  return defaultRedactor.redact(data);
}
