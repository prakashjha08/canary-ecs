import boto3
from time import sleep
from math import ceil
from canary_to_primary import alb_weight_updation, update_primary_service_td, ch_canary_capacity

import argparse
parser = argparse.ArgumentParser(description="Arguments for canary deployment")
parser.add_argument("--region")
parser.add_argument("--cluster_name")
parser.add_argument("--canary_service")
parser.add_argument("--primary_service")
parser.add_argument("--percent_increase")
parser.add_argument("--wish_to_switch_to_primary")

args = parser.parse_args()

# Access the values of the parsed arguments
region = args.region
cluster_name = args.cluster_name
canary_service = args.canary_service
primary_service = args.primary_service
percent_increase = int(args.percent_increase)
wish_to_switch_to_primary = args.wish_to_switch_to_primary.lower()

session = boto3.session.Session(region_name=region)

elb = session.client('elbv2')
ecs = session.client('ecs')
ecs_auto_scaling = session.client('application-autoscaling')
sts = session.client('sts')
id = sts.get_caller_identity()
waiter = ecs.get_waiter('services_stable')


lb = elb.describe_load_balancers()


##Cluster ARN
cluster = 'arn:aws:ecs:{}:{}:cluster/{}'.format(region,id['Account'],cluster_name)

###Function to update canary service
def primary_ecs(*args):
    global primary_service
    primary_service_details = ecs.describe_services(
        cluster = args[2],
        services=[
            primary_service
        ],
    )
    primary_service_scalable_targets = ecs_auto_scaling.describe_scalable_targets(
        ServiceNamespace = 'ecs',
        ResourceIds = [
            "service/{}/{}".format(cluster_name,primary_service_details['services'][0]['serviceArn'].split('/')[-1])
        ]
    )
    primary_service_desired = int(primary_service_details['services'][0]['desiredCount'])
    primary_service_max = int(primary_service_scalable_targets['ScalableTargets'][0]['MaxCapacity'])

    primary_tg = primary_service_details['services'][0]['loadBalancers'][0]['targetGroupArn']

    canary_desired = 2 if int(ceil((args[1] / 100) * primary_service_desired)) < 2 else int(ceil((args[1] / 100) * primary_service_desired))
    canary_min = canary_desired
    canary_max = 4 if int(ceil((args[1] / 100) * primary_service_max)) < 4 else int(ceil((args[1] / 100) * primary_service_max))

    ###Update Canary service

    ecs.update_service(
        cluster = args[2],
        service=args[0],
        desiredCount=canary_desired
    )

    canary_resource_id = "service/{}/{}".format(args[2].split('/')[-1],args[0])

    ecs_auto_scaling.register_scalable_target(
        ServiceNamespace='ecs',
        ResourceId=canary_resource_id,
        ScalableDimension='ecs:service:DesiredCount',
        MinCapacity=canary_min,
        MaxCapacity=canary_max,
    )

    canary_service_details = ecs.describe_services(
        cluster = args[2],
        services=[
            args[0]
        ],
    )
    canary_tg_arn = canary_service_details['services'][0]['loadBalancers'][0]['targetGroupArn']
    
    return canary_tg_arn, primary_tg

canary_tg, primary_tg = primary_ecs(canary_service, percent_increase,cluster)



###Function to update TGs associated with Canary ECS service
def tg_update(*args):
    listener_arns = []
    listener_primary_service = elb.describe_target_groups(
    TargetGroupArns = [args[1]]
    )
    print(listener_primary_service)
    listener = elb.describe_listeners(
        LoadBalancerArn = listener_primary_service['TargetGroups'][0]['LoadBalancerArns'][0]
    )

    for j in listener['Listeners']:
        listener_arns.append(j['ListenerArn'])
    print("LISTENER:",listener_arns)
    rule_arns = []
    for i in listener_arns:
        rules = elb.describe_rules(
            ListenerArn = i
        )
        for i in listener_arns:
            rules = elb.describe_rules(
                ListenerArn = i
            )
            for rule in rules['Rules']:
                    if rule["Actions"][0]["Type"] == "forward":
                        if any(args[0].split('/',2)[1] in string for string in [str(z) for y in (x.values() for x in rule['Actions'][0]['ForwardConfig']['TargetGroups']) for z in y]) :
                            for tg in rule['Actions'][0]['ForwardConfig']['TargetGroups']:
                                if tg['TargetGroupArn'] == args[1]:
                                    rule_arns.append(rule['RuleArn'])
                                if tg['TargetGroupArn'] == args[0]:
                                    j = tg['Weight']
    print("Current weight on canary:", j)

    for i in rule_arns:
        rule_arn_details = elb.describe_rules(
            RuleArns=[
                i,
            ]
        )
        if rule_arn_details["Rules"][0]["Actions"][0]["Type"] == "forward":
            elb.modify_rule(
                    RuleArn=i,
                    Actions=[
                        {
                            'Type': 'forward',
                            'ForwardConfig': {
                                'TargetGroups': [
                                {
                                    'TargetGroupArn': args[1],
                                    'Weight': 100 - percent_increase
                                },
                                {
                                    'TargetGroupArn': args[0],
                                    'Weight': percent_increase
                                },
                            ],
                        }
                    }
                ]
            )
    print(f"{percent_increase}% traffic moved to canary tg")

    return rule_arns

try:
    print(f"Waiting for service {canary_service} to be stable")
    waiter.wait(
    cluster = cluster,
    services = [
        canary_service,
    ],
    WaiterConfig={
        'Delay': 15,
        'MaxAttempts': 40
    }
    )
    print(f"{canary_service} is stable")
    rule_arns = tg_update(canary_tg, primary_tg)
except Exception as e:
    print("Failed due to: ",e)

if percent_increase == 100 and wish_to_switch_to_primary == "true":
    print("Waiting for primary service to be stable")
    rollback = update_primary_service_td(region,cluster,canary_service,primary_service)
    print("Rollback - ",rollback)
    if rollback == False:
        alb_weight_updation(region,rule_arns,primary_tg,canary_tg)
        ch_canary_capacity(region,cluster,canary_service)
else:
    print(f"Traffic to be passed to canary is {percent_increase}%")
