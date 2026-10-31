// All the inputs in one card, shown at the top of the Ask page once a question has been asked:
// the filters first, then the question box directly under them. The answer appears below.
// It is one <form>, so pressing Enter in any field sends the question.

import { useAskSubmit, AskFields } from "./AskBox";
import { ClearFiltersButton, FilterFields } from "./FilterForm";
import { Card } from "./ui";

export function InputPanel() {
  return (
    <Card>
      <form className="flex flex-col gap-4" onSubmit={useAskSubmit()} role="search">
        <div>
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Filters <span className="font-normal normal-case">(optional, they narrow which trials are retrieved)</span>
          </h2>
          <FilterFields trailing={<ClearFiltersButton />} />
        </div>
        <AskFields />
      </form>
    </Card>
  );
}
