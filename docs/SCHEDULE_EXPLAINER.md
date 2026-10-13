# Schedule explainer

Shows why the scheduler made each decision for this week, in plain English. Output is one HTML file you double-click to open. No server or internet needed to view it.

It is **read-only**. It builds the schedules in memory and never writes to the DB, never saves centre hours and never touches RabbitMQ.

## Options

```
python app.py explain_schedule -c configprod.py [options]
```

| Option | What it does |
|---|---|
| `--html FILE` | Write the page (data inside) to `FILE` |
| `--json FILE` | Write the raw data. Open `tools/schedule_explainer.html` and pick this file to view it |
| `--strategy greedy\|optimal` | Override `GAP_FILL_STRATEGY` for this run only |
| `--patient ID [ID ...]` | Only these patients |
| `--with-names` | Show patient names. Off by default. **The file then has patient names in it, don't share it widely** |

A text summary is always printed to the terminal.

## Getting it to staging and prod

Nothing extra to deploy. The explainer is part of the scheduler code, and the Dockerfile copies the whole repo (including `tools/schedule_explainer.html`) into the image. No new env vars, configmap entries or DB changes.

It goes out the same way as any change:

1. Merge into `scheduler_staging`. `cd-stg.yml` builds and rolls out the staging image.
2. Run it on staging (below) and check the output looks right.
3. Merge into `scheduler_prod`. `cd-prod.yml` builds and rolls out the prod image.

Until it's merged, run it from a branch archive instead (see [Before it's in the image](#before-its-in-the-image-from-a-branch)).

## Running it

It needs the environment's DB, so run it on the server in a throwaway pod made from that environment's image and configmap. Both environments are on the same cluster, only the names differ:

| | Staging | Prod |
|---|---|---|
| Deploys from branch | `scheduler_staging` | `scheduler_prod` |
| Namespace | `staging` | `default` |
| Deployment | `scheduler-service-stg` | `scheduler-service-dev` |
| ConfigMap | `scheduler-service-stg-env` | `scheduler-service-dev-env` |

Don't run it inside the live scheduler pod. It runs uvicorn with `reload=True`, and on staging it has a 512Mi limit, so a full schedule build there can get it killed. The throwaway pod gets no traffic (the Service doesn't select it) and starts no consumers.

### Once this code is in the image

```
ssh <user>@<server>

# pick one
NS=staging DEPLOY=scheduler-service-stg CM=scheduler-service-stg-env    # staging
NS=default DEPLOY=scheduler-service-dev CM=scheduler-service-dev-env    # prod

IMG=$(kubectl get deploy $DEPLOY -n $NS -o jsonpath='{.spec.template.spec.containers[0].image}')
kubectl run explain-tmp -n $NS --image="$IMG" --restart=Never --overrides='{"spec":{"containers":[{"name":"explain-tmp","image":"'"$IMG"'","command":["sleep","3600"],"envFrom":[{"configMapRef":{"name":"'"$CM"'"}}],"env":[{"name":"TZ","value":"Asia/Singapore"}]}]}}'
kubectl wait --for=condition=Ready pod/explain-tmp -n $NS --timeout=120s

kubectl exec -n $NS explain-tmp -- python app.py explain_schedule -c configprod.py --html /tmp/schedule.html
kubectl cp $NS/explain-tmp:/tmp/schedule.html ~/schedule.html

kubectl delete pod explain-tmp -n $NS
exit
```

Then on your laptop:

```
scp <user>@<server>:~/schedule.html .
ssh <user>@<server> 'rm -f ~/schedule.html'
open schedule.html        # or double-click it
```

### Before it's in the image (from a branch)

Make an archive of the branch on your laptop:

```
git archive --format=tar.gz --prefix=explain-src/ -o explain-src.tar.gz <branch>
scp explain-src.tar.gz <user>@<server>:~/
```

On the server, unpack it and add the logger config (it's gitignored so the archive doesn't have it):

```
rm -rf ~/explain-src && tar xzf ~/explain-src.tar.gz -C ~
printf 'import logging\nlogger = logging.getLogger("pear_schedule")\n' > ~/explain-src/pear_schedule/logger/config.py
```

Set `NS`/`DEPLOY`/`CM` and create the pod as above, then copy the code in and run from there:

```
kubectl cp ~/explain-src $NS/explain-tmp:/tmp/explain
kubectl exec -n $NS explain-tmp -- sh -c "cd /tmp/explain && python app.py explain_schedule -c configprod.py --html /tmp/schedule.html"
kubectl cp $NS/explain-tmp:/tmp/schedule.html ~/schedule.html
kubectl delete pod explain-tmp -n $NS
```

Clean up the server after copying the file back:

```
rm -rf ~/explain-src ~/explain-src.tar.gz ~/schedule.html
```

### Check you left nothing behind

```
kubectl get pods -n $NS     # no explain-tmp, the scheduler pod's age unchanged
```

### Prod

- It reads the same tables as one `/generate`. Fine to run any time, but avoid running it over and over during centre hours.
- The output has real patient schedules (and names with `--with-names`). Keep it off shared drives and chats, delete it from the server after copying, and never commit it.
- Try the same command on staging first if anything in the code changed since the last prod run.

## Reading the page

- **Centre overview**: how much Free and Easy there is, the reasons and what would reduce it. "Could the scheduler have filled more?" says if any Free and Easy was avoidable (a scheduler problem) or all of it came from the data.
- **Patients**: pick a patient, click any block to see why it's there. The panel on the right sums up the patient's week: rules broken, things that look odd but follow the rules, liked activities that weren't scheduled, things that couldn't be added.
- **Data to fix**: problems found in the activity data, most important first, each with a suggested fix. Send this tab to whoever owns the activity data.
- **Show technical details**: shows the reason codes and which stage wrote each slot, for debugging.

Block markers: ♥ liked, 💊 medication given, ⓘ looks unusual but follows the rules, red outline means something to check.

### Things that look like bugs but aren't

| What you see | Why |
|---|---|
| Patient has an activity they dislike | A doctor recommended it. Recommendation comes before preference |
| Patient is in a group they didn't ask for | Added to reach the group's minimum size, or the weekly group target. Never someone who dislikes it or is excluded |
| Activity replaced on some days | An adhoc request for those days |
| Activity moved to another time | Moved to make room for a routine |
| Compulsory activity missing | Another compulsory activity is set at the same time. Shown as a data clash under Data to fix |

## Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: pear_schedule.logger.config` | Create the logger config as shown above |
| `... has no <!-- EXPLAIN_DATA --> placeholder` | `tools/schedule_explainer.html` is missing or old. Run from the repo root of the same branch |
| Page opens with a file picker | It was opened without data (the plain viewer). Pick a `--json` file, or use `--html` instead |
| Week looks wrong | The pod must have `TZ=Asia/Singapore`, "this week" is based on the pod's clock |
| `configmap ... not found` | Wrong `NS`/`CM` pair, check them against the table in [Running it](#running-it) |
