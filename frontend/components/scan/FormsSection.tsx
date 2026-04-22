import { Check, X } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import type { FormPurpose, FormReport } from "@/lib/types";

const PURPOSE_STYLE: Record<FormPurpose, string> = {
  collection:     "bg-amber-500/10 text-amber-700 dark:text-amber-400",
  search:         "bg-sky-500/10 text-sky-700 dark:text-sky-400",
  authentication: "bg-violet-500/10 text-violet-700 dark:text-violet-400",
  unknown:        "bg-slate-500/10 text-slate-600 dark:text-slate-400",
};

const PURPOSE_LABEL: Record<FormPurpose, string> = {
  collection:     "collection",
  search:         "search",
  authentication: "auth",
  unknown:        "unknown",
};

export function FormsSection({ report }: { report: FormReport }) {
  const s = report.summary;
  if (report.forms.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Forms</CardTitle>
          <CardDescription>No forms detected on the crawled pages.</CardDescription>
        </CardHeader>
      </Card>
    );
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle>Forms</CardTitle>
        <CardDescription>
          {s.total_forms ?? 0} form(s) — {s.forms_collecting_pii ?? 0} collect personal data,{" "}
          {s.forms_with_consent_checkbox ?? 0} have a consent checkbox, {s.forms_with_privacy_link ?? 0} link to
          the privacy policy.
          {((s.forms_search ?? 0) > 0 || (s.forms_authentication ?? 0) > 0) && (
            <span className="text-xs"> · {s.forms_search ?? 0} search, {s.forms_authentication ?? 0} auth (excluded from PII counts)</span>
          )}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Accordion type="multiple" className="w-full">
          {report.forms.map((f, i) => (
            <AccordionItem key={i} value={`f${i}`}>
              <AccordionTrigger>
                <div className="flex flex-1 items-center justify-between pr-3">
                  <div className="flex items-center gap-2 text-left">
                    <Badge variant="outline" className="font-mono text-[10px]">{f.method}</Badge>
                    <Badge className={`text-[10px] uppercase ${PURPOSE_STYLE[f.purpose]}`}>
                      {PURPOSE_LABEL[f.purpose]}
                    </Badge>
                    <span className="truncate text-sm">{f.page_url}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    {f.issues.length > 0 ? (
                      <Badge className="bg-risk-high/10 text-risk-high">
                        {f.issues.length} issue{f.issues.length === 1 ? "" : "s"}
                      </Badge>
                    ) : (
                      <Badge className="bg-risk-low/10 text-risk-low">OK</Badge>
                    )}
                  </div>
                </div>
              </AccordionTrigger>
              <AccordionContent>
                <div className="space-y-3 text-sm">
                  <div>
                    <div className="text-xs uppercase text-muted-foreground">Action</div>
                    <code className="text-xs">{f.form_action ?? "—"}</code>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Field label="Consent checkbox" ok={f.has_consent_checkbox} />
                    <Field label="Privacy link" ok={f.has_privacy_link} />
                  </div>
                  {f.collected_data.length > 0 && (
                    <div>
                      <div className="text-xs uppercase text-muted-foreground">Data collected</div>
                      <div className="mt-1 flex flex-wrap gap-1">
                        {f.collected_data.map((c) => (
                          <Badge key={c} variant="outline" className="text-xs">{c}</Badge>
                        ))}
                      </div>
                    </div>
                  )}
                  {f.legal_text_excerpt && (
                    <div>
                      <div className="text-xs uppercase text-muted-foreground">Legal text excerpt</div>
                      <blockquote className="mt-1 border-l-2 pl-3 text-xs italic text-muted-foreground">
                        {f.legal_text_excerpt}
                      </blockquote>
                    </div>
                  )}
                  {f.issues.length > 0 && (
                    <ul className="list-inside list-disc text-sm text-risk-high">
                      {f.issues.map((x, j) => <li key={j}>{x}</li>)}
                    </ul>
                  )}
                </div>
              </AccordionContent>
            </AccordionItem>
          ))}
        </Accordion>
      </CardContent>
    </Card>
  );
}

function Field({ label, ok }: { label: string; ok: boolean }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs">
      {ok ? <Check className="h-3.5 w-3.5 text-risk-low" /> : <X className="h-3.5 w-3.5 text-risk-high" />}
      {label}
    </span>
  );
}
