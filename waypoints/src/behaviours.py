# Christopher Iliffe Sprague
# sprague@kth.se
# Behaviours to use within a behaviour tree.
# https://arxiv.org/abs/1811.00426

import py_trees as pt, py_trees_ros as ptr, itertools, std_msgs.msg, copy, json

class Sequence(pt.composites.Selector):

    """
    Reactive sequence overidding sequence with memory, py_trees' only available sequence.
    """

    def __init__(self, name="Sequence", children=None):
        super(Sequence, self).__init__(name=name, children=children)

    def tick(self):
        """
        Run the tick behaviour for this selector. Note that the status
        of the tick is always determined by its children, not
        by the user customised update function.
        Yields:
            :class:`~py_trees.behaviour.Behaviour`: a reference to itself or one of its children
        """
        self.logger.debug("%s.tick()" % self.__class__.__name__)
        # Required behaviour for *all* behaviours and composites is
        # for tick() to check if it isn't running and initialise
        if self.status != pt.common.Status.RUNNING:
            # selectors dont do anything specific on initialisation
            #   - the current child is managed by the update, never needs to be 'initialised'
            # run subclass (user) handles
            self.initialise()
        # run any work designated by a customised instance of this class
        self.update()
        previous = self.current_child
        for child in self.children:
            for node in child.tick():
                yield node
                if node is child:
                    if node.status == pt.common.Status.RUNNING or node.status == pt.common.Status.FAILURE:
                        self.current_child = child
                        self.status = node.status
                        if previous is None or previous != self.current_child:
                            # we interrupted, invalidate everything at a lower priority
                            passed = False
                            for child in self.children:
                                if passed:
                                    if child.status != pt.common.Status.INVALID:
                                        child.stop(pt.common.Status.INVALID)
                                passed = True if child == self.current_child else passed
                        yield self
                        return
        # all children succeded, set succed ourselves and current child to the last bugger who failed us
        self.status = pt.common.Status.SUCCESS
        try:
            self.current_child = self.children[-1]
        except IndexError:
            self.current_child = None
        yield self

class SetBlackboardVariable(pt.behaviours.Running):
    """
    Set the specified variable on the blackboard.
    Usually we set variables from inside other behaviours, but can
    be convenient to set them from a behaviour of their own sometimes so you
    don't get blackboard logic mixed up with more atomic behaviours.
    Args:
        name (:obj:`str`): name of the behaviour
        variable_name (:obj:`str`): name of the variable to set
        variable_value (:obj:`any`): value of the variable to set
    .. todo:: overwrite option, leading to possible failure/success logic.
    """
    def __init__(self,
                 name="Set Blackboard Variable",
                 variable_name="dummy",
                 variable_value=None
                 ):
        """
        :param name: name of the behaviour
        :param variable_name: name of the variable to set
        :param value_name: value of the variable to set
        """
        super(SetBlackboardVariable, self).__init__(name)
        self.variable_name = variable_name
        self.variable_value = variable_value

    def initialise(self):
        self.blackboard = pt.blackboard.Blackboard()
        self.blackboard.set(self.variable_name, self.variable_value, overwrite=True)

class Counter(pt.behaviour.Behaviour):

    # A simple counter

    def __init__(self, n, name='Counter', reset=False):

        # count
        self.i = 0
        self.n = n

        # resetting
        self.reset = reset

        # become a behaviour
        super(Counter, self).__init__(name)

    def update(self):

        # increment the count
        self.i += 1

        # react to the result
        return pt.common.Status.FAILURE if self.i <= self.n else pt.common.Status.SUCCESS

    def terminate(self, status):
        self.i = 0 if status == pt.common.Status.SUCCESS and self.reset else self.i

class SetNextWaypoint(pt.behaviour.Behaviour):

    def __init__(self):

        # blackboard
        self.bb = pt.blackboard.Blackboard()

        # become a behaviour
        super(SetNextWaypoint, self).__init__("Set next waypoint!")

    def update(self):

        # set current waypoint to the next one
        self.bb.set("goal_waypoint", self.bb.get("goal_waypoint") + 1)
        return pt.common.Status.RUNNING

class AtFinalWaypoint(pt.behaviour.Behaviour):

    def __init__(self):

        # blackboard
        self.bb = pt.blackboard.Blackboard()

        # become a behaviour
        super(AtFinalWaypoint, self).__init__("At final waypoint?")

    def update(self):

        # current progress
        i = self.bb.get("goal_waypoint")
        n = self.bb.get("n_waypoints")
        self.feedback_message = "At waypoint {} of {}".format(i, n)
        
        # react to result
        return pt.common.Status.SUCCESS if i == n else pt.common.Status.FAILURE
            
class GoTo(pt.behaviour.Behaviour):

    def __init__(self):

        # blackboard
        self.bb = pt.blackboard.Blackboard()

        # become a behaviour
        super(GoTo, self).__init__("Go to waypoint!")

    def update(self):

        # NOTE: There needs to be an actual action in here
        
        # current waypoint
        i = self.bb.get("goal_waypoint")
        self.feedback_message = "Going to waypoint {}".format(i)

        # always running if preconditions are met
        return pt.common.Status.RUNNING

class SynchroniseMission(ptr.subscribers.Handler):

    def __init__(self):

        # blackboard
        self.bb = pt.blackboard.Blackboard()

        # first execution
        self.synched = False

        # become a behaviour
        super(SynchroniseMission, self).__init__(
            name="Synchronise mission!",
            topic_name="/plan_db",
            topic_type=std_msgs.msg.String,   
        )

    def update(self):
        
        with self.data_guard:

            if self.msg == None and not self.synched:
                self.feedback_message = "Waiting for first plan."
                return pt.common.Status.RUNNING

            elif self.msg == None and self.synched:
                self.feedback_message = "No new plan."
                return pt.common.Status.SUCCESS

            else:
                self.feedback_message = "Got new plan"
                self.bb.set("plan", self.clean(str(self.msg)))
                self.synched = True
                return pt.common.Status.SUCCESS
                

    @staticmethod
    def clean(plan):

        # load the pretty json file
        #f = open(fname, 'r').read()
        f = plan

        # clean
        f = f.replace(' ', '')
        f = f.replace('\\n', '')
        f = f.replace('\\"', '"')
        f = f.replace('"\\', '"')
        f = f.replace('\\', '')

        # remove
        f = f.split(',"transitions":')[0]
        f = f.split('"maneuvers":')[1]
        f = f.replace('\n', '')

        # convert to json
        f = json.loads(f)

        # save
        '''
        if sfname is not None:
            with open(sfname, 'w') as sf:
                json.dump(f, sf, sort_keys=True, indent=4)
        '''

        # return the json dictionary
        return f